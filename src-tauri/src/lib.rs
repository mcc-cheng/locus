// Locus Tauri shell (Phase 7.1).
//
// On launch a splash window is shown while we: spawn the frozen Python sidecar,
// wait (up to 15s) for it to write its port file and answer GET /health, then
// open the main window with the resolved API base injected as
// `window.__LOCUS_API__`. If the sidecar fails to come up, the splash shows the
// logs and a Retry button. The sidecar is killed when the main window closes.

use std::fs::{self, File};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

struct SidecarProc(Mutex<Option<Child>>);

const STARTUP_TIMEOUT_SECS: u64 = 15;

fn sidecar_binary(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .resolve(
            "locus-sidecar/locus-sidecar",
            tauri::path::BaseDirectory::Resource,
        )
        .map_err(|e| format!("cannot locate bundled sidecar: {e}"))
}

fn start_sidecar(app: &tauri::AppHandle) -> Result<String, String> {
    let bin = sidecar_binary(app)?;
    let data = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&data).ok();
    let warehouse = data.join("warehouse");
    fs::create_dir_all(&warehouse).ok();

    let port_file = data.join("sidecar.port");
    let log_file = data.join("sidecar.log");
    let _ = fs::remove_file(&port_file);

    let log = File::create(&log_file).map_err(|e| e.to_string())?;
    let child = Command::new(&bin)
        .env("LOCUS_DATA", &warehouse)
        .env("LOCUS_PORT_FILE", &port_file)
        .stdout(Stdio::from(log.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(log))
        .spawn()
        .map_err(|e| format!("failed to start sidecar: {e}"))?;

    if let Some(state) = app.try_state::<SidecarProc>() {
        *state.0.lock().unwrap() = Some(child);
    }

    let deadline = Instant::now() + Duration::from_secs(STARTUP_TIMEOUT_SECS);
    loop {
        if Instant::now() > deadline {
            let logs = fs::read_to_string(&log_file).unwrap_or_default();
            return Err(format!(
                "The Locus engine did not start within {STARTUP_TIMEOUT_SECS}s.\n\n{logs}"
            ));
        }
        if let Ok(p) = fs::read_to_string(&port_file) {
            let p = p.trim();
            if !p.is_empty() {
                let url = format!("http://127.0.0.1:{p}");
                if ureq::get(&format!("{url}/health"))
                    .timeout(Duration::from_millis(500))
                    .call()
                    .is_ok()
                {
                    return Ok(url);
                }
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn open_main(app: &tauri::AppHandle, api_url: &str) -> Result<(), String> {
    let script = format!(
        "window.__LOCUS_API__ = {};",
        serde_json::to_string(api_url).unwrap()
    );
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Biomedical Data Aggregator")
        .inner_size(1280.0, 840.0)
        .min_inner_size(900.0, 600.0)
        .center()
        .initialization_script(&script)
        .build()
        .map_err(|e| e.to_string())?;
    if let Some(splash) = app.get_webview_window("splash") {
        let _ = splash.close();
    }
    Ok(())
}

fn boot(app: tauri::AppHandle) {
    match start_sidecar(&app) {
        Ok(url) => {
            if let Err(e) = open_main(&app, &url) {
                let _ = app.emit("sidecar-error", e);
            }
        }
        Err(e) => {
            let _ = app.emit("sidecar-error", e);
        }
    }
}

#[tauri::command]
fn retry(app: tauri::AppHandle) {
    std::thread::spawn(move || boot(app));
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(SidecarProc(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![retry])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || boot(handle));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    if let Some(state) = window.app_handle().try_state::<SidecarProc>() {
                        if let Some(mut child) = state.0.lock().unwrap().take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Locus");
}

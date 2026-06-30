/** The Annulus AI brand mark — the app icon, served from /icon.png. */
export function AnnulusLogo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <img
      src="/icon.png"
      alt="Annulus AI"
      className={className}
      draggable={false}
    />
  );
}

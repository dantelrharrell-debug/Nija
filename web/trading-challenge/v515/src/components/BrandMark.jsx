/**
 * BrandMark — the NIJA mark drawn as the animated gold SVG (still, no spin).
 * Replaces the logo image file, which has a solid white background and showed
 * as a white box on dark pages. Same sizing contract as the image it replaces:
 * size comes from an explicit `size`, else style.height / style.width, else 48.
 */
import NIJALogoAnimated from "./NIJALogoAnimated.jsx";

function toPx(value) {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const n = parseFloat(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export default function BrandMark({ alt = "NIJA AI Trading", style = {}, className = "", size }) {
  const { height, width, objectFit, mixBlendMode, maxWidth, ...rest } = style;
  const px = size ?? toPx(height) ?? toPx(width) ?? 48;

  return (
    <span
      role="img"
      aria-label={alt}
      className={className}
      style={{
        display: "inline-flex",
        flexShrink: 0,
        lineHeight: 0,
        maxWidth: "100%",
        ...rest,
      }}
    >
      <NIJALogoAnimated size={px} still />
    </span>
  );
}

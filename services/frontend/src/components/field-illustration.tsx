// Generic field drawing shown where a plot has no photo. Decorative only.
export function FieldIllustration({ height = 140 }: { height?: number }) {
  return (
    <svg
      aria-hidden
      width="100%"
      height={height}
      viewBox="0 0 320 140"
      preserveAspectRatio="xMidYMid slice"
      className="block"
    >
      <rect width="320" height="140" fill="#EADFC8" />
      <circle cx="262" cy="34" r="16" fill="#D9B66A" />
      <path d="M0 72 Q80 44 170 66 T320 58 V140 H0Z" fill="#A3B57F" />
      <path d="M0 92 Q110 74 210 88 T320 84 V140 H0Z" fill="#6E8A4E" />
      <path d="M0 112 Q120 100 320 108 V140 H0Z" fill="#8B6B47" />
      <path
        d="M20 140 L120 108 M80 140 L150 107 M140 140 L180 107 M200 140 L210 108 M260 140 L240 108 M310 140 L270 109"
        stroke="#6F5235"
        strokeWidth="2"
      />
    </svg>
  );
}

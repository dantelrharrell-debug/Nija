/**
 * NIJALogoAnimated — pure SVG, zero PNG, zero white.
 *
 * THREE layers for true "wreath passes in front AND behind" effect:
 *   z1 — WREATH BACK HALF  (spinning, behind sword)
 *   z2 — SWORD + TEXT      (still, always visible)
 *   z3 — WREATH FRONT HALF (spinning, in front of sword)
 *
 * The wreath front and back halves share the same rotateY animation
 * so they move together. A clipPath splits left/right so when the
 * wreath rotates, one side appears to go behind and the other in front.
 *
 * Sword + text: all gold, faithful to original logo.
 * Wreath: wide — branches sit outside text bounding box.
 */

// Single wreath SVG shared between both layers via children prop
function WreathSVG() {
  return (
    <svg viewBox="0 0 260 280" width="100%" height="100%"
         style={{ display: "block" }}>
      <defs>
        <linearGradient id="lL" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%"   stopColor="#FFF8C0"/>
          <stop offset="22%"  stopColor="#F5D040"/>
          <stop offset="55%"  stopColor="#C8980F"/>
          <stop offset="100%" stopColor="#7A5510"/>
        </linearGradient>
        <linearGradient id="lR" x1="100%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%"   stopColor="#FFF8C0"/>
          <stop offset="22%"  stopColor="#F5D040"/>
          <stop offset="55%"  stopColor="#C8980F"/>
          <stop offset="100%" stopColor="#7A5510"/>
        </linearGradient>
      </defs>

      {/* LEFT BRANCH */}
      <g>
        <path d="M74,32 Q44,62 26,110 Q20,148 46,186 Q62,202 84,210"
              stroke="#F5D040" strokeWidth="2" fill="none" opacity="0.45"/>
        {[
          [70,30,-40,14,5.2],[55,46,-57,15,5.5],[40,66,-73,15.5,5.6],
          [30,88,-86,15.5,5.6],[24,112,-95,15.5,5.4],[26,136,-106,15,5.3],
          [34,158,-120,14.5,5.1],[48,176,-136,14,4.9],
          [64,190,-151,13,4.6],[80,200,-165,12,4.3],[96,206,-175,11,4.0],
        ].map(([x,y,r,rx,ry],i) => (
          <g key={i} transform={`translate(${x},${y}) rotate(${r})`}>
            <ellipse rx={rx} ry={ry} fill="url(#lL)"/>
            <line x1={-rx+1} y1="0" x2={rx-1} y2="0"
                  stroke="#8B6810" strokeWidth="0.9" opacity="0.7"/>
          </g>
        ))}
        <circle cx="70" cy="26" r="5" fill="#FFE566"/>
        <circle cx="69" cy="25" r="2.2" fill="#FFF8C0" opacity="0.7"/>
      </g>

      {/* RIGHT BRANCH */}
      <g>
        <path d="M186,32 Q216,62 234,110 Q240,148 214,186 Q198,202 176,210"
              stroke="#F5D040" strokeWidth="2" fill="none" opacity="0.45"/>
        {[
          [190,30,40,14,5.2],[205,46,57,15,5.5],[220,66,73,15.5,5.6],
          [230,88,86,15.5,5.6],[236,112,95,15.5,5.4],[234,136,106,15,5.3],
          [226,158,120,14.5,5.1],[212,176,136,14,4.9],
          [196,190,151,13,4.6],[180,200,165,12,4.3],[164,206,175,11,4.0],
        ].map(([x,y,r,rx,ry],i) => (
          <g key={i} transform={`translate(${x},${y}) rotate(${r})`}>
            <ellipse rx={rx} ry={ry} fill="url(#lR)"/>
            <line x1={-rx+1} y1="0" x2={rx-1} y2="0"
                  stroke="#8B6810" strokeWidth="0.9" opacity="0.7"/>
          </g>
        ))}
        <circle cx="190" cy="26" r="5" fill="#FFE566"/>
        <circle cx="191" cy="25" r="2.2" fill="#FFF8C0" opacity="0.7"/>
      </g>

      {/* BOTTOM BOW */}
      <g>
        <path d="M96,210 Q130,228 164,210" stroke="#F5D040" strokeWidth="2.4" fill="none"/>
        <path d="M96,210 Q88,220 82,216 Q78,212 82,208"
              stroke="#F5D040" strokeWidth="1.7" fill="none"/>
        <path d="M164,210 Q172,220 178,216 Q182,212 178,208"
              stroke="#F5D040" strokeWidth="1.7" fill="none"/>
        <path d="M118,224 Q130,238 142,224"
              stroke="#F5D040" strokeWidth="2" fill="none" opacity="0.8"/>
        {[
          [98,214,-20,10,3.8,"lL"],[130,224,0,10,3.8,"lL"],
          [162,214,20,10,3.8,"lR"],[80,210,-42,9,3.4,"lL"],
          [180,210,42,9,3.4,"lR"],[112,230,-10,8.5,3.2,"lL"],
          [148,230,10,8.5,3.2,"lR"],
        ].map(([x,y,r,rx,ry,g],i) => (
          <g key={i} transform={`translate(${x},${y}) rotate(${r})`}>
            <ellipse rx={rx} ry={ry} fill={`url(#${g})`}/>
          </g>
        ))}
      </g>
    </svg>
  );
}

export default function NIJALogoAnimated({ size = 220, className = "", still = false }) {
  // Spin animation duration — "none" when used as a static logo mark
  const spinDur = still ? "0s" : "3.5s";
  const spinAnim = still ? "none" : `nijCoin ${spinDur} linear infinite`;

  return (
    <div
      className={className}
      style={{
        width: size,
        height: size,
        position: "relative",
        flexShrink: 0,
        background: "transparent",
        perspective: size * 6,
      }}
    >
      {/* Ambient glow */}
      <div style={{
        position: "absolute", inset: "-16%", borderRadius: "50%",
        background: "radial-gradient(circle, rgba(245,208,64,0.25) 0%, transparent 62%)",
        animation: "nijGlow 3.8s ease-in-out infinite",
        pointerEvents: "none", zIndex: 0,
      }} />

      {/* ═════════════════════════════════════════
          LAYER 1 — WREATH BACK (spins, z:1)
          Clipped to the LEFT half of the viewBox
          so it appears to go behind the sword
         ═════════════════════════════════════════ */}
      <div style={{
        position: "absolute", inset: 0, zIndex: 1,
        animation: spinAnim,
        transformStyle: "preserve-3d",
        pointerEvents: "none",
        /* clip to left half — this half goes "behind" when facing us */
        clipPath: "inset(0 50% 0 0)",
      }}>
        <WreathSVG />
      </div>

      {/* ═════════════════════════════════════════
          LAYER 2 — SWORD + TEXT (still, z:2)
          Always in the middle, always readable
         ═════════════════════════════════════════ */}
      <svg viewBox="0 0 260 280" width="100%" height="100%"
           style={{ position: "absolute", inset: 0, zIndex: 2, display: "block" }}>
        <defs>
          {/* All-gold sword — matches original logo */}
          <linearGradient id="sg" x1="20%" y1="0%" x2="80%" y2="100%">
            <stop offset="0%"   stopColor="#FFF8C0"/>
            <stop offset="18%"  stopColor="#F5D040"/>
            <stop offset="45%"  stopColor="#E8B800"/>
            <stop offset="78%"  stopColor="#9A6F1A"/>
            <stop offset="100%" stopColor="#6B4A0D"/>
          </linearGradient>
          <linearGradient id="sg2" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#9A6F1A"/>
            <stop offset="35%"  stopColor="#F5D040"/>
            <stop offset="50%"  stopColor="#FFF8C0"/>
            <stop offset="65%"  stopColor="#F5D040"/>
            <stop offset="100%" stopColor="#9A6F1A"/>
          </linearGradient>
          {/* Multi-color steel blade — blue-chrome-silver */}
          <linearGradient id="bladeg" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#2A1800"/>
            <stop offset="10%"  stopColor="#4A3000"/>
            <stop offset="25%"  stopColor="#8B6810"/>
            <stop offset="40%"  stopColor="#D4A62A"/>
            <stop offset="48%"  stopColor="#FFE566"/>
            <stop offset="50%"  stopColor="#FFFDE8"/>
            <stop offset="52%"  stopColor="#FFE566"/>
            <stop offset="60%"  stopColor="#D4A62A"/>
            <stop offset="75%"  stopColor="#8B6810"/>
            <stop offset="90%"  stopColor="#4A3000"/>
            <stop offset="100%" stopColor="#2A1800"/>
          </linearGradient>
          {/* Fuller groove highlight */}
          <linearGradient id="fullerg" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#8B6810"/>
            <stop offset="50%"  stopColor="#FFF0A0"/>
            <stop offset="100%" stopColor="#8B6810"/>
          </linearGradient>
          {/* Gold brick text — horizontal facets like a cast gold bar */}
          <linearGradient id="textg" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#FFFDE8"/>  {/* top specular edge */}
            <stop offset="6%"   stopColor="#FFF0A0"/>  {/* bright top face */}
            <stop offset="14%"  stopColor="#FFD700"/>  {/* upper gold */}
            <stop offset="24%"  stopColor="#E8B800"/>  {/* mid-upper */}
            <stop offset="34%"  stopColor="#C8980F"/>  {/* true gold mid */}
            <stop offset="44%"  stopColor="#FFE566"/>  {/* bright center band — the "shine" */}
            <stop offset="50%"  stopColor="#FFF0A0"/>  {/* peak specular */}
            <stop offset="56%"  stopColor="#FFE566"/>  {/* bright center fade */}
            <stop offset="65%"  stopColor="#C8980F"/>  {/* lower mid */}
            <stop offset="75%"  stopColor="#A67800"/>  {/* lower shadow */}
            <stop offset="86%"  stopColor="#7A5200"/>  {/* deep shadow */}
            <stop offset="94%"  stopColor="#4A3000"/>  {/* very dark base */}
            <stop offset="100%" stopColor="#2A1800"/>  {/* bottom edge */}
          </linearGradient>
          {/* Sub-text gold — simpler brick shine */}
          <linearGradient id="subtg2" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#FFF5C0"/>
            <stop offset="20%"  stopColor="#FFD700"/>
            <stop offset="42%"  stopColor="#FFE566"/>
            <stop offset="58%"  stopColor="#FFD700"/>
            <stop offset="80%"  stopColor="#8B6010"/>
            <stop offset="100%" stopColor="#4A2E00"/>
          </linearGradient>
          <linearGradient id="subtg" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#FFE566"/>
            <stop offset="55%"  stopColor="#C8980F"/>
            <stop offset="100%" stopColor="#8B6010"/>
          </linearGradient>
          <filter id="gf" x="-15%" y="-15%" width="130%" height="130%">
            <feGaussianBlur stdDeviation="0.5" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>

        {/* cx = 130 */}

        {/* ══════════════════════════════════════════════
            SWORD: top-to-bottom correct order
            Pommel (top) → Grip/Handle → Guard → Long Blade (bottom)
           ══════════════════════════════════════════════ */}

        {/* ── POMMEL — round wheel on top of grip, y:10–28 ── */}
        <circle cx="130" cy="19" r="10" fill="url(#sg)" filter="url(#gf)"/>
        {/* Rim ring */}
        <circle cx="130" cy="19" r="10" fill="none" stroke="#F5D040" strokeWidth="1" opacity="0.5"/>
        <circle cx="130" cy="19" r="6.5" fill="none" stroke="#FFE566" strokeWidth="0.6" opacity="0.35"/>
        {/* Boss centre */}
        <circle cx="130" cy="19" r="4" fill="url(#sg)" filter="url(#gf)"/>
        <ellipse cx="128.5" cy="17.5" rx="2" ry="2" fill="#FFF8C0" opacity="0.5"/>
        {/* Pommel to grip tang */}
        <rect x="128.5" y="28" width="3" height="4" fill="url(#sg2)"/>

        {/* ── CROSS GUARD — wider to match Excalibur blade, y:66–77 ── */}
        <path d="M110,66 Q120,63 130,64 Q140,63 150,66 Q148,77 130,76 Q112,77 110,66 Z"
              fill="url(#sg)" filter="url(#gf)"/>
        <path d="M112,66 Q130,62 148,66" stroke="#FFF8C0" strokeWidth="1.1" fill="none" opacity="0.5"/>
        <path d="M112,76 Q130,78 148,76" stroke="#6B4A0D" strokeWidth="0.7" fill="none" opacity="0.4"/>

        {/* Left hook — wider reach */}
        <path d="M110,66 Q103,61 98,64 Q93,68 96,74 Q99,78 105,75 Q108,73 110,70"
              fill="url(#sg)" filter="url(#gf)"/>
        <ellipse cx="94.5" cy="70" rx="3.5" ry="4.5" fill="url(#sg2)" filter="url(#gf)"/>
        <ellipse cx="93.5" cy="68.5" rx="1.4" ry="1.6" fill="#FFF8C0" opacity="0.5"/>

        {/* Right hook — wider reach */}
        <path d="M150,66 Q157,61 162,64 Q167,68 164,74 Q161,78 155,75 Q152,73 150,70"
              fill="url(#sg)" filter="url(#gf)"/>
        <ellipse cx="165.5" cy="70" rx="3.5" ry="4.5" fill="url(#sg2)" filter="url(#gf)"/>
        <ellipse cx="166.5" cy="68.5" rx="1.4" ry="1.6" fill="#FFF8C0" opacity="0.5"/>

        {/* ── GRIP / HANDLE — y:32–66, black leather + red/black diagonal wrap ── */}
        <path d="M127.5,32 Q126,49 127.5,66 L132.5,66 Q134,49 132.5,32 Z" fill="#0F1829"/>
        <path d="M127.5,32 Q126.2,49 127.5,66" stroke="#000" strokeWidth="1.2" fill="none" opacity="0.9"/>
        <path d="M132.5,32 Q133.8,49 132.5,66" stroke="#000" strokeWidth="1.2" fill="none" opacity="0.9"/>

        <defs>
          <clipPath id="gripClip">
            <path d="M127.5,32 Q126,49 127.5,66 L132.5,66 Q134,49 132.5,32 Z"/>
          </clipPath>
        </defs>
        <g clipPath="url(#gripClip)">
          {[
            {y1:31,  y2:34.5, col:"#8B0000"},
            {y1:34.5,y2:37,   col:"#1A0000"},
            {y1:37,  y2:40.5, col:"#B22222"},
            {y1:40.5,y2:43,   col:"#0F1829"},
            {y1:43,  y2:46.5, col:"#CC2200"},
            {y1:46.5,y2:49,   col:"#1A0000"},
            {y1:49,  y2:52.5, col:"#8B0000"},
            {y1:52.5,y2:55,   col:"#0F1829"},
            {y1:55,  y2:58.5, col:"#B22222"},
            {y1:58.5,y2:62,   col:"#1A0000"},
            {y1:62,  y2:65.5, col:"#8B0000"},
            {y1:65.5,y2:68,   col:"#0F1829"},
          ].map((b,i) => (
            <polygon key={i}
              points={`125,${b.y1} 135,${b.y1-3} 135,${b.y2-3} 125,${b.y2}`}
              fill={b.col}/>
          ))}
          <rect x="129.5" y="32" width="1" height="34" fill="#444" opacity="0.35"/>
        </g>

        {/* Gold stitching — left */}
        {[33.5,37,40.5,44,47.5,51,54.5,58,61.5,65].map(y => (
          <circle key={y} cx="127.8" cy={y} r="0.65" fill="#E8B800" opacity="0.85"/>
        ))}
        {/* Gold stitching — right */}
        {[33.5,37,40.5,44,47.5,51,54.5,58,61.5,65].map(y => (
          <circle key={y} cx="132.2" cy={y} r="0.65" fill="#E8B800" opacity="0.85"/>
        ))}

        {/* ══ EXCALIBUR BROAD DOUBLE-EDGED BLADE
            Wide at guard (22px), tapers gently to acute point.
            Diamond cross-section: left face + right face,
            bright center ridge spine, both edges sharp & glinting. ══ */}

        {/* LEFT FACE — wide, diamond cross-section left side */}
        <polygon points="119,76 130,76 130,262" fill="url(#bladeg)" opacity="0.97"/>
        {/* RIGHT FACE — mirrored */}
        <polygon points="130,76 141,76 130,262" fill="url(#bladeg)" opacity="0.97"
                 transform="scale(-1,1) translate(-260,0)"/>

        {/* Center ridge — bright spine running full length */}
        <line x1="130" y1="76" x2="130" y2="261"
              stroke="#FFFDE8" strokeWidth="1.4" opacity="0.65"/>

        {/* Left sharp edge — bright glinting line */}
        <line x1="119" y1="77" x2="130" y2="261"
              stroke="#FFF0A0" strokeWidth="0.9" opacity="0.7"/>
        {/* Right sharp edge */}
        <line x1="141" y1="77" x2="130" y2="261"
              stroke="#FFF0A0" strokeWidth="0.9" opacity="0.7"/>

        {/* Left fuller groove (blood groove) — runs 2/3 down blade */}
        <polygon points="125,76 127.5,76 130,220" fill="url(#fullerg)" opacity="0.6"/>
        {/* Right fuller groove */}
        <polygon points="132.5,76 135,76 130,220" fill="url(#fullerg)" opacity="0.6"/>

        {/* Dark edge bevels — gives the blade real depth */}
        <polygon points="119,76 121,76 130,262" fill="#2A1800" opacity="0.4"/>
        <polygon points="139,76 141,76 130,262" fill="#2A1800" opacity="0.4"/>

        {/* Broad mid-blade specular reflection band */}
        <ellipse cx="130" cy="168" rx="5" ry="38" fill="#FFF0A0" opacity="0.1"/>

        {/* Tip — sharp acute point */}
        <polygon points="128,258 130,264 132,258" fill="#FFF0A0" opacity="0.55"/>

        {/* ══ TEXT ══ */}

        {/* ══ TEXT — matches original logo exactly ══
            NIJA: large bold serif, same font as original (Times New Roman bold)
            AI TRADING: smaller, spaced wide — textLength forces both to same width (86px)
            Both centred on x=130 */}

        {/* Shared text width — forces NIJA and AI TRADING to identical span */}
        {/* NIJA renders ~86px wide at fontSize 52; AI TRADING stretched to same */}

        {/* ── NIJA — 5-layer gold, large serif bold, wide spacing ── */}
        <text x="130" y="146" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="52" fontWeight="900"
          textLength="150" lengthAdjust="spacing"
          fill="none" stroke="#000000" strokeWidth="8" strokeLinejoin="round"
          paintOrder="stroke">NIJA</text>
        <text x="130" y="146" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="52" fontWeight="900"
          textLength="150" lengthAdjust="spacing"
          fill="none" stroke="#2A1400" strokeWidth="5" strokeLinejoin="round">NIJA</text>
        <text x="130" y="146" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="52" fontWeight="900"
          textLength="150" lengthAdjust="spacing"
          fill="none" stroke="#8B5E00" strokeWidth="2.8" strokeLinejoin="round">NIJA</text>
        <text x="130" y="146" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="52" fontWeight="900"
          textLength="150" lengthAdjust="spacing"
          fill="none" stroke="#FFE566" strokeWidth="0.9" strokeLinejoin="round"
          opacity="0.8">NIJA</text>
        <text x="130" y="146" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="52" fontWeight="900"
          textLength="150" lengthAdjust="spacing"
          fill="url(#textg)">NIJA</text>

        {/* ── AI TRADING — same total width as NIJA (150px) ── */}
        <text x="130" y="163" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="13" fontWeight="700"
          textLength="150" lengthAdjust="spacing"
          fill="none" stroke="#000000" strokeWidth="5" strokeLinejoin="round"
          paintOrder="stroke">AI TRADING</text>
        <text x="130" y="163" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="13" fontWeight="700"
          textLength="150" lengthAdjust="spacing"
          fill="none" stroke="#2A1400" strokeWidth="2.8" strokeLinejoin="round">AI TRADING</text>
        <text x="130" y="163" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="13" fontWeight="700"
          textLength="150" lengthAdjust="spacing"
          fill="none" stroke="#F5D040" strokeWidth="1" strokeLinejoin="round"
          opacity="0.75">AI TRADING</text>
        <text x="130" y="163" textAnchor="middle"
          fontFamily="'Times New Roman','Georgia',serif"
          fontSize="13" fontWeight="700"
          textLength="150" lengthAdjust="spacing"
          fill="url(#subtg2)">AI TRADING</text>

      </svg>

      {/* ═════════════════════════════════════════
          LAYER 3 — WREATH FRONT (spins, z:3)
          Clipped to the RIGHT half of the viewBox
          so it appears to pass IN FRONT of the sword
         ═════════════════════════════════════════ */}
      <div style={{
        position: "absolute", inset: 0, zIndex: 3,
        animation: spinAnim,
        transformStyle: "preserve-3d",
        pointerEvents: "none",
        /* clip to right half — this half comes in front */
        clipPath: "inset(0 0 0 50%)",
      }}>
        <WreathSVG />
      </div>

      <style>{`
        @keyframes nijCoin {
          from { transform: rotateY(0deg); }
          to   { transform: rotateY(360deg); }
        }
        @keyframes nijGlow {
          0%, 100% { opacity: 0.45; transform: scale(1); }
          50%       { opacity: 1;   transform: scale(1.08); }
        }
      `}</style>
    </div>
  );
}

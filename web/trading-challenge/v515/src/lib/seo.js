/**
 * SEO helpers — sets canonical URL, robots meta, title, and description for each route.
 * Call from useEffect with no dependencies so it runs once on mount.
 * Never imports PocketBase or any analytics — pure DOM manipulation.
 */

const BASE = "https://nijaaitrading.com";

// Matches the per-route map in index.html so client-side navigation stays in sync
const ROUTE_META = {
  "/": { title: "NIJA AI Trading LLC | Learn to Trade With Discipline", desc: "Trading education for new traders — structured courses, paper trading, and risk tools before you risk real money. Education-first. Mobile app in development." },
  "/pilot": { title: "NIJA AI Trading | Apply for Pilot Access", desc: "Explore NIJA's Pilot Program and help shape the future of structured trading education." },
  "/join-nija": { title: "NIJA AI Trading | Apply for Pilot Access", desc: "Explore NIJA's Pilot Program and help shape the future of structured trading education." },
  "/trading-foundations": { title: "NIJA Trading Foundations | $99 Trading Education Course", desc: "Learn financial markets, risk management, trading psychology, paper trading, and responsible AI-assisted trading. $99 one-time purchase." },
  "/pricing": { title: "NIJA AI Trading Pricing | $99 Course & $50/mo Founding Membership", desc: "Compare NIJA AI Trading products: $99 Trading Foundations course and $50/month Founding 100 membership with 14-day free trial." },
  "/apply": { title: "Apply — NIJA Founding 100 | NIJA AI Trading LLC", desc: "Apply to become one of 100 NIJA Founding Members. Start with a 14-day free trial, then $50/month. Limited spots available." },
  "/about": { title: "About NIJA AI Trading LLC | Founder & Mission", desc: "NIJA AI Trading LLC is an independent fintech company building AI-assisted trading education and technology for new traders." },
  "/affiliate": { title: "NIJA Affiliate Program | Earn 30% Commission on Trading Education", desc: "Promote NIJA Trading Foundations and earn 30% commission on qualifying $99 sales through the NIJA ClickBank affiliate program." },
  "/investor-relations": { title: "Investor Relations | NIJA AI Trading LLC", desc: "NIJA AI Trading LLC investor information, growth projections, and how to request investor materials." },
  "/support": { title: "Customer Support | NIJA AI Trading LLC", desc: "Get help with NIJA Trading Foundations, course access, billing questions, and technical support." },
  "/brokerages": { title: "Open a Brokerage Account | NIJA AI Trading LLC", desc: "Create a supported brokerage account with Kraken, Coinbase, OKX, or Alpaca using NIJA's official referral links." },
  "/vs/invest-ai": { title: "NIJA vs Invest AI | Trading Education Comparison", desc: "Compare NIJA AI Trading with Invest AI — see which platform offers better education, risk tools, and value for new traders." },
  "/vs/youtube-trading-courses": { title: "NIJA vs Free YouTube Trading Courses | Why Structure Matters", desc: "Compare NIJA Trading Foundations with free YouTube trading content — structured education vs scattered videos." },
  "/shop": { title: "NIJA AI Trading Official Merch | Shop", desc: "Shop official NIJA AI Trading merchandise — unisex shirts and women's cropped tees, made to order and shipped worldwide." },
  "/partners": { title: "NIJA Partners & Ecosystem | NIJA AI Trading LLC", desc: "Meet the companies and creators partnering with NIJA AI Trading to build a better trading education ecosystem." },
  "/videos": { title: "Trading Videos & Market Analysis | NIJA AI Trading", desc: "Watch NIJA AI Trading videos covering market analysis, trading strategies, risk management, and AI-assisted decision-making." },
  "/review": { title: "Share Your NIJA Experience | NIJA AI Trading", desc: "Already a NIJA member? Share your trading education experience and help other new traders make an informed decision." },
  "/affiliate-creator": { title: "NIJA Creator Affiliate Program | Earn as a Content Creator", desc: "Content creators and influencers — join the NIJA affiliate program and earn commissions promoting structured trading education." },
  "/become-a-sponsor": { title: "Become a NIJA Sponsor | NIJA AI Trading LLC", desc: "Partner with NIJA AI Trading as a sponsor and reach a growing audience of disciplined new traders and fintech enthusiasts." },
  "/partner-with-nija": { title: "Partner With NIJA | NIJA AI Trading LLC", desc: "Explore strategic partnership opportunities with NIJA AI Trading — brokerages, fintech tools, and education platforms welcome." },
  "/start-beta": { title: "Start Your NIJA Free Trial | Founding 100 Membership", desc: "Start your 14-day free NIJA Founding 100 membership trial — then $50/month. Limited to the first 100 members. Apply now." },
  "/future": { title: "The Future of NIJA AI Trading | Roadmap & Vision", desc: "See where NIJA AI Trading is headed — upcoming AI tools, mobile apps, and the long-term vision for structured trading education." },
  "/free": { title: "Free Trader Readiness Assessment | NIJA AI Trading", desc: "Take the free NIJA Trader Readiness Assessment and get your personalized score, risk profile, trading checklist, paper-trading challenge, and next-step roadmap." },
  "/free-trader-assessment": { title: "Free Trader Readiness Assessment | NIJA AI Trading", desc: "Take the free NIJA Trader Readiness Assessment and get your personalized score, risk profile, trading checklist, paper-trading challenge, and next-step roadmap." },
  "/changelog": { title: "NIJA AI Trading Changelog | Product Updates", desc: "Track every update to the NIJA AI Trading platform — new features, improvements, and fixes as the product evolves." },

  // ── NIJA Academy ──────────────────────────────────────────────────────────
  "/academy": { title: "NIJA Academy | Free Financial Literacy for All Ages", desc: "Free financial education for kids, teens, and adults. Age-appropriate courses on money, investing, budgeting, and generational wealth. No cost for ages 5–17." },
  "/academy/courses": { title: "All NIJA Academy Courses | Free Financial Education", desc: "Browse every NIJA Academy course — free financial literacy for kids ages 5–17, adult investing foundations, and the $99 Trading Foundations course." },
  "/academy/future-wealth-builders": { title: "NIJA Future Wealth Builders | Black Youth Financial Empowerment", desc: "Free financial literacy, entrepreneurship, and generational wealth education for Black youth ages 5–17. Mentor, partner, or sponsor the next generation." },
  "/academy/ages-5-8": { title: "Little Money Makers | Financial Literacy for Kids Ages 5–8 | NIJA Academy", desc: "Free, age-appropriate money education for young children. Learn what money is, how saving works, and the difference between needs and wants — through games and stories." },
  "/academy/ages-9-12": { title: "Junior Investors | Financial Education for Kids Ages 9–12 | NIJA Academy", desc: "Free financial literacy for pre-teens. Budgeting, banking basics, and your first introduction to investing and compound interest." },
  "/academy/ages-13-17": { title: "Teen Wealth Builders | Financial Education for Teenagers | NIJA Academy", desc: "Free financial literacy for teens. Stock markets, entrepreneurship, credit, income streams, and building wealth before adulthood." },
  "/academy/ages-18-25": { title: "Young Professionals Financial Education | NIJA Academy", desc: "Free financial foundation for young adults — managing first income, student debt, emergency funds, and beginning to invest." },
  "/academy/ages-26-45": { title: "Wealth Accelerators | Adult Financial Education | NIJA Academy", desc: "Free financial education for adults building wealth — home ownership, retirement planning, investing strategies, and growing family finances." },
  "/academy/ages-46-65": { title: "Legacy Builders | Retirement & Wealth Education | NIJA Academy", desc: "Free retirement and wealth education for adults 46–65. Maximize savings, plan distributions, protect assets, and prepare for a secure retirement." },
  "/academy/ages-66-plus": { title: "Wisdom & Wealth | Senior Financial Education | NIJA Academy", desc: "Free financial education for seniors. Managing retirement income, protecting savings, legacy planning, and avoiding financial scams." },
  "/academy/faq": { title: "NIJA Academy FAQ | Common Questions About Free Financial Education", desc: "Answers to common questions about NIJA Academy — who can enroll, how it works, privacy for minors, and how to get your child started." },
  "/academy/scholarships": { title: "NIJA Academy Scholarships | Free Financial Education Grants", desc: "Apply for a NIJA Academy scholarship for sponsored youth financial literacy education, programs, and mentorship opportunities." },
  "/academy/partners": { title: "NIJA Academy Community Partners | Schools, Churches & Organizations", desc: "Partner with NIJA Academy to bring free financial literacy education to your school, church, youth program, or community organization." },
};

function setMeta(name, content) {
  let el = document.querySelector(`meta[name="${name}"]`);
  if (el) el.setAttribute("content", content);
}
function setOg(prop, content) {
  let el = document.querySelector(`meta[property="${prop}"]`);
  if (el) el.setAttribute("content", content);
}

/**
 * setPageSEO({ path, noindex, title, desc })
 * - Sets canonical, robots, title, and description for the current route.
 * - title/desc override the ROUTE_META lookup when supplied explicitly.
 */
export function setPageSEO({ path = "/", noindex = false, title, desc } = {}) {
  // Canonical
  let canonical = document.querySelector('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement("link");
    canonical.rel = "canonical";
    document.head.appendChild(canonical);
  }
  canonical.href = BASE + path;

  // Robots
  let robots = document.querySelector('meta[name="robots"]');
  if (!robots) {
    robots = document.createElement("meta");
    robots.name = "robots";
    document.head.appendChild(robots);
  }
  robots.content = noindex ? "noindex, nofollow" : "index, follow";

  // Title + description — use explicit args, fall back to route map, leave unchanged if neither
  const route = ROUTE_META[path] || {};
  const resolvedTitle = title || route.title;
  const resolvedDesc = desc || route.desc;

  if (resolvedTitle) {
    document.title = resolvedTitle;
    setOg("og:title", resolvedTitle);
    setMeta("twitter:title", resolvedTitle);
  }
  if (resolvedDesc) {
    setMeta("description", resolvedDesc);
    setOg("og:description", resolvedDesc);
    setMeta("twitter:description", resolvedDesc);
  }

  // og:url
  setOg("og:url", BASE + path);
}

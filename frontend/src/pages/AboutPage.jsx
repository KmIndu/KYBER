/**
 * About Us page — KYBER product info and Team JEDI showcase.
 * Integrated as a React route to match the app's look and feel.
 */

import { useEffect, useRef } from "react";

/* ── Starfield Canvas Component ── */
function Starfield() {
  const canvasRef = useRef(null);
  const starsRef = useRef([]);
  const rafRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const STAR_COUNT = 180;

    function resize() {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    }

    function init() {
      resize();
      starsRef.current = Array.from({ length: STAR_COUNT }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: 0.3 + Math.random() * 1.0,
        phase: Math.random() * Math.PI * 2,
        speed: 0.5 + Math.random() * 1.2,
      }));
    }

    function draw(time) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const star of starsRef.current) {
        const alpha = 0.2 + 0.6 * ((Math.sin(time * 0.001 * star.speed + star.phase) + 1) / 2);
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(200, 255, 230, ${alpha})`;
        ctx.fill();
      }
      rafRef.current = requestAnimationFrame(draw);
    }

    init();
    rafRef.current = requestAnimationFrame(draw);

    const handleResize = () => {
      resize();
      starsRef.current.forEach((s) => {
        s.x = Math.random() * canvas.width;
        s.y = Math.random() * canvas.height;
      });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ zIndex: 0 }}
    />
  );
}

/* ── Section Divider ── */
function Divider() {
  return (
    <div
      className="w-full h-px opacity-20"
      style={{ background: "linear-gradient(90deg, transparent, #00FF9F, #9D4EDD, transparent)" }}
    />
  );
}

/* ── Animated Crystal ── */
function KyberCrystal() {
  return (
    <div className="relative flex items-center justify-center h-[320px]">
      <div className="absolute w-[240px] h-[240px] rounded-full bg-[radial-gradient(circle,rgba(0,255,159,0.15),transparent_70%)]" />
      <div
        className="w-[120px] h-[180px] animate-pulse"
        style={{
          clipPath: "polygon(50% 0%, 100% 30%, 85% 100%, 15% 100%, 0% 30%)",
          background: "linear-gradient(180deg, #00FF9F, #00E6CC)",
          filter: "blur(0.5px)",
        }}
      />
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="absolute rounded-full border border-[rgba(0,255,159,0.15)] animate-ping"
          style={{
            width: `${160 + i * 60}px`,
            height: `${160 + i * 60}px`,
            animationDelay: `${i * 1}s`,
            animationDuration: "3s",
          }}
        />
      ))}
    </div>
  );
}

/* ── Feature Card ── */
function FeatureCard({ icon, title, description }) {
  return (
    <div className="group relative bg-white dark:bg-[#202127] border border-gray-200 dark:border-[#2e2e32] rounded-xl p-6 overflow-hidden transition-all duration-300 hover:border-[#00FF9F]/30 hover:shadow-lg hover:shadow-[#00FF9F]/5 hover:-translate-y-1">
      <div className="absolute top-0 left-0 w-0 h-[2px] bg-gradient-to-r from-[#00FF9F] to-[#00E6CC] transition-all duration-400 group-hover:w-full" />
      <div className="w-10 h-10 rounded-lg bg-[#00FF9F]/10 flex items-center justify-center text-xl mb-4">
        {icon}
      </div>
      <h3 className="text-xs font-semibold uppercase text-[#00FF9F] tracking-wide mb-2">
        {title}
      </h3>
      <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] text-sm leading-relaxed">
        {description}
      </p>
    </div>
  );
}

/* ── Team Card ── */
function TeamCard({ image, name, role, details, variant = "green" }) {
  const isGreen = variant === "green";
  const borderHover = isGreen ? "hover:border-[#00FF9F]/35" : "hover:border-[#9D4EDD]/40";
  const shadowHover = isGreen ? "hover:shadow-[#00FF9F]/5" : "hover:shadow-[#9D4EDD]/5";
  const avatarBg = isGreen ? "from-[rgba(0,255,159,0.04)]" : "from-[rgba(157,78,221,0.04)]";
  const badgeColor = isGreen ? "text-[#00FF9F] border-[#00FF9F]/25 bg-[#00FF9F]/5" : "text-[#9D4EDD] border-[#9D4EDD]/25 bg-[#9D4EDD]/5";
  const roleColor = isGreen ? "text-[#00FF9F]" : "text-[#9D4EDD]";

  return (
    <div className={`bg-white dark:bg-[#202127] border border-gray-200 dark:border-[#2e2e32] rounded-xl overflow-hidden transition-all duration-300 hover:-translate-y-1.5 hover:shadow-lg ${borderHover} ${shadowHover}`}>
      <div className={`h-[180px] flex items-end justify-center pb-4 relative bg-gradient-to-b ${avatarBg} to-transparent`}>
        <img src={image} alt={name} className={`w-[110px] h-[110px] rounded-full object-cover border-2 ${isGreen ? "border-[#00FF9F] shadow-[0_0_12px_rgba(0,255,159,0.5)]" : "border-[#9D4EDD] shadow-[0_0_12px_rgba(157,78,221,0.5)]"}`} />
        <span className={`absolute top-3 right-3 font-mono text-[0.55rem] tracking-wider border rounded px-2 py-0.5 ${badgeColor}`}>
          JEDI KNIGHT
        </span>
      </div>
      <div className="p-5">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] mb-1">
          {name}
        </h3>
        <p className={`font-mono text-[0.65rem] tracking-wide ${roleColor} mb-3`}>
          {role}
        </p>
        {details && (
          <ul className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] text-xs leading-relaxed space-y-1">
            {details.map((d, i) => <li key={i}>{d}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ── Why Item ── */
function WhyItem({ number, title, description }) {
  return (
    <div className="pl-5 border-l-2 border-[#00FF9F]/15 rounded-r-lg bg-white dark:bg-[#202127] p-5 transition-all duration-300 hover:border-l-[#00FF9F] hover:bg-gray-50 dark:hover:bg-[#252529]">
      <div className="text-3xl font-black text-[#00FF9F]/10 leading-none mb-2">
        {number}
      </div>
      <h3 className="text-sm font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] mb-2">
        {title}
      </h3>
      <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] text-sm leading-relaxed">
        {description}
      </p>
    </div>
  );
}

/* ── Main About Page ── */
export default function AboutPage() {
  // Scroll reveal
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("opacity-100", "translate-y-0");
            entry.target.classList.remove("opacity-0", "translate-y-6");
          }
        });
      },
      { threshold: 0.1 }
    );
    document.querySelectorAll(".reveal-item").forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return (
    <div className="relative overflow-hidden">
      {/* Starfield background */}
      <div className="fixed inset-0 pointer-events-none" style={{ zIndex: 0 }}>
        <Starfield />
      </div>

      <div className="relative" style={{ zIndex: 1 }}>
        {/* ── HERO ── */}
        <section className="min-h-[80vh] flex flex-col items-center justify-center text-center px-6 py-20">
          {/* Glow orb */}
          <div className="absolute w-[400px] h-[400px] rounded-full bg-[radial-gradient(circle,rgba(0,255,159,0.06),rgba(157,78,221,0.03)_40%,transparent_70%)] animate-pulse pointer-events-none" />

          <p className="font-mono text-xs tracking-[0.4em] text-[#00FF9F] mb-4 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            TEAM JEDI PRESENTS
          </p>
          <h1
            className="font-['Orbitron',sans-serif] font-black text-[clamp(3rem,10vw,7rem)] leading-none mb-3 reveal-item opacity-0 translate-y-6 transition-all duration-700 delay-100"
            style={{
              background: "linear-gradient(135deg, #ffffff, #00FF9F, #00E6CC)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              filter: "drop-shadow(0 0 25px rgba(0,255,159,0.25))",
            }}
          >
            KYBER
          </h1>
          <p className="font-['Orbitron',sans-serif] text-[clamp(0.7rem,2vw,1rem)] text-[#9D4EDD] tracking-[0.3em] mb-6 reveal-item opacity-0 translate-y-6 transition-all duration-700 delay-200">
            SYNTHETIC DATA FORGE
          </p>
          <p className="text-gray-400 dark:text-[rgba(235,235,245,0.45)] italic reveal-item opacity-0 translate-y-6 transition-all duration-700 delay-300">
            <span className="not-italic text-[#00FF9F]">May the Synthetic Data Be With You</span> — generating balanced data with the Force
          </p>
        </section>

        <Divider />

        {/* ── MISSION ── */}
        <section className="max-w-6xl mx-auto px-6 py-24">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
            <div className="reveal-item opacity-0 translate-y-6 transition-all duration-700">
              <p className="font-mono text-[0.7rem] tracking-[0.3em] text-[#00FF9F] mb-3 uppercase">
                OUR MISSION
              </p>
              <h2 className="text-2xl md:text-3xl font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] mb-6">
                Built by warriors. Powered by pure data.
              </h2>
              <div className="space-y-4 text-gray-500 dark:text-[rgba(235,235,245,0.6)] text-[0.95rem] leading-relaxed">
                <p>In the vast galaxy of software testing, teams struggle with incomplete, biased, and unrealistic test data. We set out to change that — forging synthetic datasets that mirror production with perfect fidelity.</p>
                <p>KYBER was born from the belief that quality data shouldn't require production access, compliance waivers, or weeks of manual crafting. A single schema should be enough to conjure thousands of realistic, constraint-aware records.</p>
                <p>Our mission is to arm every QA warrior, developer, and data engineer with the power to generate perfect test data in seconds — respecting referential integrity, business rules, and domain context.</p>
              </div>
            </div>
            <div className="reveal-item opacity-0 translate-y-6 transition-all duration-700 delay-200">
              <KyberCrystal />
            </div>
          </div>
        </section>

        <Divider />

        {/* ── FEATURES ── */}
        <section className="max-w-6xl mx-auto px-6 py-24">
          <p className="font-mono text-[0.7rem] tracking-[0.3em] text-[#00FF9F] mb-3 uppercase reveal-item opacity-0 translate-y-6 transition-all duration-700">
            THE TOOL
          </p>
          <h2 className="text-2xl md:text-3xl font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] mb-4 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            What is KYBER?
          </h2>
          <p className="max-w-[680px] text-gray-500 dark:text-[rgba(235,235,245,0.6)] mb-12 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            KYBER is an AI-powered synthetic data generation engine that transforms your schemas, specs, and feature files into production-grade test data — instantly and without compromising privacy.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {[
              { icon: "⚡", title: "High-Fidelity Generation", description: "Produces data that mirrors real-world distributions, patterns, and edge cases — indistinguishable from production datasets." },
              { icon: "⚖️", title: "Balanced by Design", description: "Ensures proportional representation across categories, demographics, and value ranges for unbiased testing coverage." },
              { icon: "🔮", title: "Privacy Preserving", description: "Zero real PII. Every record is synthetically generated — safe for shared environments, CI/CD pipelines, and demos." },
              { icon: "🛸", title: "Domain Agnostic", description: "Banking, insurance, healthcare, retail — KYBER adapts its generation strategy to any industry vertical automatically." },
              { icon: "🌐", title: "Scalable at Warp Speed", description: "From 10 rows to 1,000,000 — generation scales linearly with consistent quality and constraint adherence." },
              { icon: "🧬", title: "Schema-Aware Intelligence", description: "Understands foreign keys, check constraints, unique indexes, and data types to produce relationally coherent datasets." },
            ].map((f, i) => (
              <div key={i} className="reveal-item opacity-0 translate-y-6 transition-all duration-700" style={{ transitionDelay: `${i * 80}ms` }}>
                <FeatureCard {...f} />
              </div>
            ))}
          </div>
        </section>

        <Divider />

        {/* ── TEAM ── */}
        <section className="max-w-6xl mx-auto px-6 py-24">
          <p className="font-mono text-[0.7rem] tracking-[0.3em] text-[#00FF9F] mb-3 uppercase reveal-item opacity-0 translate-y-6 transition-all duration-700">
            THE ORDER
          </p>
          <h2 className="text-2xl md:text-3xl font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] mb-4 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            Meet Team JEDI
          </h2>
          <p className="max-w-[600px] text-gray-500 dark:text-[rgba(235,235,245,0.6)] mb-12 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            Four Jedi Knights united by a single purpose: to eliminate bad test data from the galaxy. Each brings a unique discipline to the forge.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {[
              { image: "/Avantika.png", name: "Avantika Mussady", role: "SPECIALIST DEVELOPMENT", details: ["SLF Exp – 9 Months", "CND IT Management"], variant: "green" },
              { image: "/Indu.png", name: "KM Indu", role: "ASSOCIATE ANALYST DEVELOPMENT", details: ["SLF Exp – 2.7 yrs", "CND IT Management"], variant: "purple" },
              { image: "/Paaras.png", name: "Paaras Makkar", role: "PROCESS ARCHITECT", details: ["SLF Exp – 3 yrs", "Business Excellence"], variant: "green" },
              { image: "/Jatin.png", name: "Jatin Malhotra", role: "MANAGER TRANSFORMATION", details: ["SLF Exp – 3.5 yrs", "Business Excellence"], variant: "purple" },
            ].map((member, i) => (
              <div key={i} className="reveal-item opacity-0 translate-y-6 transition-all duration-700" style={{ transitionDelay: `${i * 100}ms` }}>
                <TeamCard {...member} />
              </div>
            ))}
          </div>
        </section>

        <Divider />

        {/* ── PHILOSOPHY ── */}
        <section className="max-w-6xl mx-auto px-6 py-24">
          <p className="font-mono text-[0.7rem] tracking-[0.3em] text-[#00FF9F] mb-3 uppercase reveal-item opacity-0 translate-y-6 transition-all duration-700">
            OUR PHILOSOPHY
          </p>
          <h2 className="text-2xl md:text-3xl font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] mb-8 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            Why we built this
          </h2>

          {/* Pull quote */}
          <div className="relative text-center max-w-[700px] mx-auto mb-16 py-8 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            <span className="absolute top-0 left-1/2 -translate-x-1/2 text-7xl text-[#00FF9F]/10 leading-none select-none">&ldquo;</span>
            <p className="text-[clamp(0.9rem,2.5vw,1.2rem)] font-medium text-[#00FF9F]/85 leading-relaxed">
              The best test data is data that never existed in production — yet behaves exactly as if it did.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {[
              { number: "01", title: "Production data is dangerous", description: "Real customer data in test environments creates compliance nightmares. KYBER eliminates that risk entirely with zero-PII synthetic generation." },
              { number: "02", title: "Manual test data doesn't scale", description: "Handcrafting INSERT statements for 50 tables with foreign keys is medieval. Schema-aware automation generates thousands of consistent rows in seconds." },
              { number: "03", title: "Edge cases matter most", description: "Bugs hide at boundaries. KYBER systematically generates negative, boundary, and duplicate cases that manual testers inevitably miss." },
              { number: "04", title: "Context changes everything", description: "A \"name\" column in healthcare vs. retail means different things. Domain-aware generation produces contextually realistic values, not random strings." },
            ].map((item, i) => (
              <div key={i} className="reveal-item opacity-0 translate-y-6 transition-all duration-700" style={{ transitionDelay: `${i * 100}ms` }}>
                <WhyItem {...item} />
              </div>
            ))}
          </div>
        </section>

        <Divider />

        {/* ── CTA ── */}
        <section className="text-center px-6 py-24 relative">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[250px] rounded-full bg-[radial-gradient(circle,rgba(0,255,159,0.04),transparent_70%)] pointer-events-none" />
          <h2 className="text-2xl md:text-3xl font-semibold text-gray-900 dark:text-[rgba(255,255,245,0.86)] mb-4 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            Ready to forge your data?
          </h2>
          <p className="text-gray-500 dark:text-[rgba(235,235,245,0.6)] mb-8 reveal-item opacity-0 translate-y-6 transition-all duration-700">
            Upload a schema. Get production-grade synthetic data in seconds.
          </p>
          <a
            href="/generate"
            className="reveal-item opacity-0 translate-y-6 transition-all duration-700 inline-block font-['Orbitron',sans-serif] text-sm font-bold tracking-wider text-[#00FF9F] border-2 border-[#00FF9F] rounded-lg px-10 py-3.5 hover:bg-[#00FF9F] hover:text-[#0B0F14] hover:shadow-[0_0_20px_rgba(0,255,159,0.2)] transition-colors"
          >
            LAUNCH KYBER
          </a>
        </section>
      </div>
    </div>
  );
}

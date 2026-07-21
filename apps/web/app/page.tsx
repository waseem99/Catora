import { BrowserIntelligenceCard } from "@/components/browser-intelligence-card";

const capabilities = [
  ["Catalog ingestion", "Shopify, CSV and authorized public catalog sources"],
  ["Deterministic audit", "Traceable completeness, consistency and discoverability findings"],
  ["Buyer intents", "Explain why products confidently match—or cannot yet match—real shopper needs"],
  ["Controlled optimization", "Evidence, confidence and human approval before any catalog change"],
];

export default function Home() {
  return (
    <main>
      <nav className="shell nav">
        <strong>Catora</strong>
        <span>AI Commerce Intelligence</span>
      </nav>

      <section className="shell hero">
        <div>
          <p className="eyebrow">MVP FOUNDATION ONLINE</p>
          <h1>Make every product understandable, discoverable and measurable.</h1>
          <p className="lede">
            Catora turns large ecommerce catalogs into governed product intelligence for search,
            AI shopping and multi-market operations.
          </p>
          <div className="actions">
            <a className="primary" href="http://localhost:8000/docs">Open API</a>
            <a className="secondary" href="https://github.com/waseem99/Catora/issues/1">View roadmap</a>
          </div>
        </div>
        <div className="score-card" aria-label="Illustrative catalog health preview">
          <span>Catalog health</span>
          <strong>62%</strong>
          <div className="bar"><i /></div>
          <dl>
            <div><dt>Products</dt><dd>2,460</dd></div>
            <div><dt>Critical gaps</dt><dd>384</dd></div>
            <div><dt>Missing attributes</dt><dd>1,142</dd></div>
          </dl>
          <small>Illustrative seeded-demo metrics</small>
        </div>
      </section>

      <section className="shell capability-grid" aria-label="Core product capabilities">
        {capabilities.map(([title, text]) => (
          <article key={title}>
            <span className="indicator" />
            <h2>{title}</h2>
            <p>{text}</p>
          </article>
        ))}
      </section>

      <section className="shell intelligence-section">
        <div>
          <p className="eyebrow">PRIVATE BY DESIGN</p>
          <h2>Open-source browser intelligence, with authoritative work kept server-side.</h2>
          <p>
            Catora can use WebGPU or WebAssembly for explicitly invoked local inference. Catalog
            scoring and enterprise analytics remain deterministic and auditable on the backend.
          </p>
        </div>
        <BrowserIntelligenceCard />
      </section>
    </main>
  );
}

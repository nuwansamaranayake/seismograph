import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/instrument-serif/latin-400-italic.css";
import "@fontsource/instrument-serif/latin-400.css";
import type { Metadata } from "next";
import "../shell/globals.css";
import "./recorder.css";

const DESCRIPTION =
  "Open source statistical process control for AI systems. Run the same question many times, " +
  "chart how much the answers move, and block a release when a declared tolerance breaks.";

export const metadata: Metadata = {
  title: "Seismograph: statistical process control for AI systems",
  description: DESCRIPTION,
};

// Stated facts only: name, category, licence, price. No rating or review fields.
const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Seismograph",
  applicationCategory: "DeveloperApplication",
  operatingSystem: "Any",
  description: DESCRIPTION,
  license: "https://www.apache.org/licenses/LICENSE-2.0",
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  url: "https://github.com/nuwansamaranayake/Seismograph",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }} />
        <main>{children}</main>
      </body>
    </html>
  );
}

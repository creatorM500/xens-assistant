import "./globals.css";
import type { Metadata } from "next";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://ainslup-web.onrender.com";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: "AINSLUP | Asistente de inteligencia artificial", template: "%s | AINSLUP" },
  description: "AINSLUP es un asistente de inteligencia artificial para conversar, analizar, investigar y terminar tareas.",
  applicationName: "AINSLUP",
  keywords: ["inteligencia artificial", "asistente de IA", "AI assistant", "AINSLUP", "SVY Teck"],
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    locale: "es_ES",
    url: "/",
    siteName: "AINSLUP",
    title: "AINSLUP | Asistente de inteligencia artificial",
    description: "Conversa, analiza, investiga y convierte instrucciones en resultados con AINSLUP.",
  },
  twitter: { card: "summary", title: "AINSLUP | Asistente de inteligencia artificial", description: "Un asistente de IA para pensar y terminar tareas." },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><head><meta name="google-site-verification" content="jnHZCjxOFta_xBGguLJuai0mSY4L-2UK4-LBiSxTsME" /></head><body>{children}</body></html>;
}

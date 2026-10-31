import "./globals.css";

export const metadata = { title: "AINSLUP", description: "Tu asistente de IA para pensar y trabajar." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><head><meta name="google-site-verification" content="jnHZCjxOFta_xBGguLJuai0mSY4L-2UK4-LBiSxTsME" /></head><body>{children}</body></html>;
}

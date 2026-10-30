import "./globals.css";

export const metadata = { title: "AINSLUP", description: "Tu asistente de IA para pensar y trabajar." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><body>{children}</body></html>;
}

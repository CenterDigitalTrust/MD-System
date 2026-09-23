export const metadata = {
  title: 'MD System Verifier',
  description: 'Trustless Verification DApp',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <style dangerouslySetInnerHTML={{__html: `
          :root {
            --ink: #1a1a1a;
            --brass-bright: #d4af37;
            --paper: #f4f4f0;
          }
          body {
            background-color: var(--paper);
            color: var(--ink);
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          }
        `}} />
      </head>
      <body>{children}</body>
    </html>
  )
}

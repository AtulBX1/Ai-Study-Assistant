import type { Metadata } from "next";
import { AuthProvider } from "@/providers/auth-provider";
import { QueryProvider } from "@/providers/query-provider";
import { ThemeProvider } from "@/providers/theme-provider";
import { Toast } from "@/components/ui/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Study Assistant",
  description: "A syllabus-aligned assistant for learning from your course PDFs.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          <ThemeProvider>
            <AuthProvider>
              {children}
              <Toast />
            </AuthProvider>
          </ThemeProvider>
        </QueryProvider>
      </body>
    </html>
  );
}

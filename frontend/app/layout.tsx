import type { Metadata } from "next";
import { AppNavigation } from "@/components/AppNavigation";
import "./globals.css";

export const metadata: Metadata = {
  title: "餐饮门店分析 Agent",
  description: "面向餐饮小店的开店前潜力分析与开店后经营诊断工具"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body><AppNavigation />{children}</body>
    </html>
  );
}

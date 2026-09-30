import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "电商经营分析 | Market Pilot",
  description: "基于历史公开电商数据验证商品销售、趋势和选品分析"
};

export default function CommerceLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}

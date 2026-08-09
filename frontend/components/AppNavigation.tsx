"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const links = [
  { href: "/", label: "控制台", match: (path: string) => path === "/" },
  {
    href: "/pre-open#feasibility",
    label: "开店测算",
    match: (path: string, hash: string) => path === "/pre-open" && hash !== "#location"
  },
  {
    href: "/pre-open#location",
    label: "商圈选址",
    match: (path: string, hash: string) => path === "/pre-open" && hash === "#location"
  },
  { href: "/operating#diagnosis", label: "经营诊断", match: (path: string) => path === "/operating" },
  { href: "/#integrations", label: "集成配置", match: () => false }
];

export function AppNavigation() {
  const pathname = usePathname();
  const [hash, setHash] = useState("");

  useEffect(() => {
    const syncHash = () => setHash(window.location.hash);
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, [pathname]);

  if (pathname === "/") return null;

  return (
    <header className="app-navigation">
      <div className="app-navigation-inner">
        <Link className="app-navigation-brand" href="/" aria-label="返回 Market Pilot 控制台">
          <span>MP</span>
          <strong>Market Pilot</strong>
        </Link>
        <nav aria-label="全局导航">
          {links.map((link) => {
            const active = link.match(pathname, hash);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={active ? "is-active" : ""}
                href={link.href}
                key={link.href}
                onClick={() => setHash(link.href.includes("#") ? `#${link.href.split("#")[1]}` : "")}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

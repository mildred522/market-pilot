import path from "node:path";

export const dynamic = "force-dynamic";

export function GET() {
  if (process.env.NODE_ENV !== "development") {
    return Response.json({ detail: "not found" }, { status: 404 });
  }
  return Response.json({ contract: 1, workspace: path.resolve(process.cwd(), "..") });
}

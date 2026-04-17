import { NextResponse } from "next/server";
import { Client } from "pg";

function getPostgresConfigFromEnv(): {
  host: string;
  port: number;
  user: string;
  password: string;
  database: string;
} | null {
  const password = process.env.POSTGRES_PASSWORD;
  if (!password) {
    return null;
  }
  return {
    host: process.env.POSTGRES_HOST || "localhost",
    port: Number(process.env.POSTGRES_PORT || "5432"),
    user: process.env.POSTGRES_USER || "postgres",
    password,
    database:
      process.env.POSTGRES_DB || process.env.POSTGRES_DATABASE || "ragchat",
  };
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ docId: string }> }
) {
  const { docId } = await context.params;
  const cfg = getPostgresConfigFromEnv();
  if (!cfg) {
    return NextResponse.json(
      { error: "Postgres config missing" },
      { status: 500 }
    );
  }

  const client = new Client({
    host: cfg.host,
    port: cfg.port,
    user: cfg.user,
    password: cfg.password,
    database: cfg.database,
    connectionTimeoutMillis: 5000,
  });

  try {
    await client.connect();
    const result = await client.query<{
      file_name: string | null;
      extracted_text: string | null;
    }>(
      `SELECT file_name, extracted_text
       FROM public.documents
       WHERE id = $1::uuid
       LIMIT 1`,
      [docId]
    );

    const row = result.rows[0];
    if (!row) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }

    const fileName = (row.file_name || `${docId}.txt`).trim();
    const extractedText = row.extracted_text || "";

    return new Response(extractedText, {
      status: 200,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": `inline; filename=\"${fileName}\"`,
      },
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json(
      { error: `Failed to load document: ${detail}` },
      { status: 500 }
    );
  } finally {
    await client.end().catch(() => undefined);
  }
}

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

function escapePdfText(input: string): string {
  return input
    .replaceAll("\\", "\\\\")
    .replaceAll("(", "\\(")
    .replaceAll(")", "\\)");
}

function buildSimplePdfFromText(rawText: string): Uint8Array {
  const lines = rawText
    .replaceAll("\r\n", "\n")
    .split("\n")
    .map((line) => line.slice(0, 140))
    .slice(0, 180);

  const textCommands: string[] = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"];
  for (const line of lines) {
    textCommands.push(`(${escapePdfText(line)}) Tj`);
    textCommands.push("T*");
  }
  textCommands.push("ET");
  const contentStream = textCommands.join("\n");

  const objects = [
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
    "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    `5 0 obj\n<< /Length ${Buffer.byteLength(contentStream, "utf8")} >>\nstream\n${contentStream}\nendstream\nendobj\n`,
  ];

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [0];
  for (const obj of objects) {
    offsets.push(Buffer.byteLength(pdf, "utf8"));
    pdf += obj;
  }

  const xrefStart = Buffer.byteLength(pdf, "utf8");
  pdf += `xref\n0 ${objects.length + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (let i = 1; i <= objects.length; i++) {
    const offset = offsets[i] ?? 0;
    pdf += `${offset.toString().padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;

  return new Uint8Array(Buffer.from(pdf, "utf8"));
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

    let displayText = (row.extracted_text || "").trim();
    if (!displayText) {
      const chunkResult = await client.query<{ chunk_text: string | null }>(
        `SELECT chunk_text
         FROM public.chunks
         WHERE document_id = $1::uuid
         ORDER BY chunk_index
         LIMIT 40`,
        [docId]
      );
      displayText = chunkResult.rows
        .map((chunk) => (chunk.chunk_text || "").trim())
        .filter(Boolean)
        .join("\n\n");
    }

    if (!displayText) {
      displayText = "No text content found for this document.";
    }

    const pdfBytes = buildSimplePdfFromText(displayText);
    const pdfFileName = fileName.toLowerCase().endsWith(".pdf")
      ? fileName
      : `${fileName}.pdf`;

    const pdfArrayBuffer = Uint8Array.from(pdfBytes).buffer;
    return new Response(pdfArrayBuffer, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="${pdfFileName}"`,
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

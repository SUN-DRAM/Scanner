import { ImageResponse } from "next/og";

import { getScanBySlug } from "@/lib/api";
import { gradeTone } from "@/lib/format";
import type { Grade } from "@/types/contract";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "SUN-DRAM Scanner result";

const TONE_COLOR: Record<ReturnType<typeof gradeTone>, string> = {
  pass: "#0E9F6E",
  warn: "#E4A11B",
  alert: "#D7263D",
};

interface OpengraphImageProps {
  params: Promise<{ slug: string }>;
}

export default async function OpengraphImage({ params }: OpengraphImageProps) {
  const { slug } = await params;

  let hostname = slug;
  let grade: Grade | null = null;
  let headline = "TLS and DNS scan result";

  try {
    const scan = await getScanBySlug(slug);
    hostname = scan.hostname;
    grade = scan.overall_grade;
    headline = scan.headline ?? headline;
  } catch {
    // Scan not found or not ready yet — render the generic card below
    // rather than failing the whole image request.
  }

  const color = grade ? TONE_COLOR[gradeTone(grade)] : "#5A6B7C";

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        backgroundColor: "#F6F8FA",
        padding: "72px",
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ display: "flex", fontSize: 28, color: "#5A6B7C" }}>SUN-DRAM Scanner</div>
      <div
        style={{
          display: "flex",
          fontSize: 56,
          fontWeight: 700,
          color: "#0B1B2B",
          marginTop: 20,
        }}
      >
        {hostname}
      </div>
      <div style={{ display: "flex", alignItems: "center", marginTop: 48 }}>
        {grade ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 150,
              height: 150,
              borderRadius: "50%",
              border: `12px solid ${color}`,
              fontSize: 64,
              fontWeight: 700,
              color,
            }}
          >
            {grade}
          </div>
        ) : null}
        <div
          style={{
            display: "flex",
            marginLeft: grade ? 40 : 0,
            fontSize: 30,
            color: "#0B1B2B",
            maxWidth: 820,
          }}
        >
          {headline}
        </div>
      </div>
    </div>,
    { ...size },
  );
}

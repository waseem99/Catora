import { ImageResponse } from "next/og";

export const runtime = "edge";

const CATEGORY_LABELS: Record<string, string> = {
  sofas: "Sofas",
  sectionals: "Sectionals",
  chairs: "Chairs",
  recliners: "Recliners",
  "dining-tables": "Dining Tables",
  desks: "Desks",
  storage: "Storage",
  beds: "Beds",
  "outdoor-seating": "Outdoor Seating",
  "coffee-tables": "Coffee Tables",
};

const CATEGORY_ACCENTS: Record<string, string> = {
  sofas: "#76E0BC",
  sectionals: "#9BD4FF",
  chairs: "#F5C36B",
  recliners: "#B8A6FF",
  "dining-tables": "#FF9F8A",
  desks: "#91D7E8",
  storage: "#B7D77A",
  beds: "#D6B3FF",
  "outdoor-seating": "#7ED6A8",
  "coffee-tables": "#F2B67A",
};

function normalizeFilename(filename: string): string {
  return filename
    .toLowerCase()
    .replace(/\.png$/, "")
    .replace(/[^a-z0-9-]/g, "");
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ filename: string }> },
) {
  const { filename } = await context.params;
  const categoryKey = normalizeFilename(filename);
  const categoryLabel = CATEGORY_LABELS[categoryKey] ?? "Furniture";
  const accent = CATEGORY_ACCENTS[categoryKey] ?? "#76E0BC";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#061713",
          color: "#F5F7F6",
          padding: "86px",
          fontFamily: "Arial, sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div
            style={{
              fontSize: 34,
              letterSpacing: 7,
              fontWeight: 700,
              color: accent,
            }}
          >
            NORTHSTAR LIVING
          </div>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 22,
              background: accent,
            }}
          />
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: "100%",
            height: 560,
            borderRadius: 44,
            border: `3px solid ${accent}`,
            background: "#0C2922",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
            }}
          >
            <div
              style={{
                width: 460,
                height: 180,
                borderRadius: 42,
                background: accent,
                opacity: 0.94,
              }}
            />
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                width: 390,
                marginTop: 18,
              }}
            >
              <div style={{ width: 28, height: 95, background: accent }} />
              <div style={{ width: 28, height: 95, background: accent }} />
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              fontSize: 82,
              lineHeight: 1,
              fontWeight: 800,
              letterSpacing: -3,
            }}
          >
            {categoryLabel}
          </div>
          <div
            style={{
              marginTop: 22,
              fontSize: 30,
              color: "#B8CCC6",
              letterSpacing: 2,
            }}
          >
            DEMO CATALOG · PRODUCT VIEW
          </div>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 1200,
      headers: {
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    },
  );
}

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const gitShaPattern = /^[0-9a-f]{40}$/;
const digestPattern = /^sha256:[0-9a-f]{64}$/;

function value(name: string): string {
  return process.env[name]?.trim() ?? "";
}

export async function GET() {
  const gitSha = value("CATORA_RELEASE_GIT_SHA").toLowerCase();
  const ciRunId = value("CATORA_RELEASE_CI_RUN_ID");
  const imageTag = value("CATORA_RELEASE_IMAGE_TAG");
  const imageDigest = value("CATORA_RELEASE_IMAGE_DIGEST").toLowerCase();
  const previousImage = value("CATORA_RELEASE_PREVIOUS_IMAGE");

  return NextResponse.json(
    {
      component: "web",
      git_sha: gitSha,
      ci_run_id: ciRunId,
      image_tag: imageTag,
      image_digest: imageDigest,
      previous_image: previousImage,
      complete:
        gitShaPattern.test(gitSha) &&
        ciRunId.length > 0 &&
        imageTag.length > 0 &&
        digestPattern.test(imageDigest),
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  IdentityCandidateRefreshResponseSchema,
  ProductIdentityCandidateListResponseSchema,
  ProductIdentitySchema,
  type ProductIdentityCandidate,
  type ProductIdentityCandidateListResponse,
} from "@catora/contracts";
import { apiRequest, type AuthUser } from "@/lib/auth";
import {
  identityCandidatesPath,
  linkProductIdentityPath,
  refreshIdentityCandidatesPath,
  rejectIdentityCandidatePath,
} from "@/lib/catalog";
import styles from "./identity-review-queue.module.css";

type Props = { workspaceId: string };

export function IdentityReviewQueue({ workspaceId }: Props) {
  const [response, setResponse] = useState<ProductIdentityCandidateListResponse | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      apiRequest<unknown>(identityCandidatesPath(workspaceId), {
        signal: controller.signal,
      }),
      apiRequest<AuthUser>("/api/v1/auth/me", {
        signal: controller.signal,
      }),
    ])
      .then(([candidatePayload, authUser]) => {
        setResponse(ProductIdentityCandidateListResponseSchema.parse(candidatePayload));
        setUser(authUser);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "Unable to load identity candidates");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [workspaceId]);

  const membership = user?.memberships.find((item) => item.workspace_id === workspaceId);
  const canManage = membership?.role === "owner" || membership?.role === "admin";

  async function reloadCandidates() {
    const payload = await apiRequest<unknown>(identityCandidatesPath(workspaceId));
    setResponse(ProductIdentityCandidateListResponseSchema.parse(payload));
  }

  async function refreshCandidates() {
    setBusyId("refresh");
    setError(null);
    setNotice(null);
    try {
      const payload = await apiRequest<unknown>(refreshIdentityCandidatesPath(workspaceId), {
        method: "POST",
      });
      const summary = IdentityCandidateRefreshResponseSchema.parse(payload);
      await reloadCandidates();
      setNotice(
        `${summary.candidates_created} created, ${summary.candidates_updated} updated, ` +
          `${summary.candidates_superseded} superseded.`,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to refresh candidates");
    } finally {
      setBusyId(null);
    }
  }

  async function acceptCandidate(candidate: ProductIdentityCandidate) {
    const reason = reasons[candidate.id]?.trim();
    if (!reason || reason.length < 3) {
      setError("Add a short review reason before accepting a candidate.");
      return;
    }
    setBusyId(candidate.id);
    setError(null);
    setNotice(null);
    try {
      const payload = await apiRequest<unknown>(
        linkProductIdentityPath(workspaceId, candidate.left_product.id),
        {
          method: "POST",
          body: JSON.stringify({
            target_product_id: candidate.right_product.id,
            candidate_id: candidate.id,
            reason,
          }),
        },
      );
      const identity = ProductIdentitySchema.parse(payload);
      await reloadCandidates();
      setNotice(`Linked ${identity.members.length} market product records.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to link products");
    } finally {
      setBusyId(null);
    }
  }

  async function rejectCandidate(candidate: ProductIdentityCandidate) {
    const reason = reasons[candidate.id]?.trim();
    if (!reason || reason.length < 3) {
      setError("Add a short review reason before rejecting a candidate.");
      return;
    }
    setBusyId(candidate.id);
    setError(null);
    setNotice(null);
    try {
      await apiRequest<unknown>(rejectIdentityCandidatePath(workspaceId, candidate.id), {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await reloadCandidates();
      setNotice("Candidate rejected and retained in the audit history.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to reject candidate");
    } finally {
      setBusyId(null);
    }
  }

  if (loading && !response) {
    return <p className="loading-state">Loading identity review queue…</p>;
  }

  return (
    <section className="catalog-panel">
      <header className="catalog-header">
        <div>
          <p className="eyebrow">IDENTITY REVIEW</p>
          <h1>Duplicate candidates</h1>
          <p className="lede">
            Review evidence before linking the same commercial product across markets. Source
            records, prices, URLs and copy remain separate.
          </p>
        </div>
        <div className="detail-actions">
          {canManage ? (
            <button
              className="secondary-button"
              disabled={busyId !== null}
              onClick={refreshCandidates}
              type="button"
            >
              {busyId === "refresh" ? "Refreshing…" : "Refresh candidates"}
            </button>
          ) : null}
          <Link className="secondary" href={`/workspace/${workspaceId}/products`}>
            Products
          </Link>
        </div>
      </header>

      {!canManage ? (
        <p className={styles.readOnlyNote}>
          Candidate evidence is visible to workspace members. Only owners and admins can link or
          reject identities.
        </p>
      ) : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {notice ? <p className="form-success" role="status">{notice}</p> : null}

      <div className="catalog-summary">
        <span>{response?.total ?? 0} pending candidates</span>
        <span>Algorithmic suggestions only</span>
      </div>

      <div className={styles.candidateList}>
        {response?.items.map((candidate) => (
          <article className={styles.candidate} key={candidate.id}>
            <header>
              <div className={styles.pair}>
                <ProductReference
                  workspaceId={workspaceId}
                  product={candidate.left_product}
                />
                <span aria-hidden="true">↔</span>
                <ProductReference
                  workspaceId={workspaceId}
                  product={candidate.right_product}
                />
              </div>
              <div className={styles.score}>
                <strong>{(candidate.score_basis_points / 100).toFixed(1)}%</strong>
                <span>{candidate.match_type}</span>
              </div>
            </header>

            <ul className={styles.signals} aria-label="Candidate evidence signals">
              {candidate.signals.map((signal) => (
                <li key={`${signal.kind}:${signal.value ?? ""}`}>
                  <strong>{signal.kind.replaceAll("_", " ")}</strong>
                  <span>{signal.value ?? "Matched"}</span>
                </li>
              ))}
            </ul>

            {canManage ? (
              <div className={styles.actions}>
                <label>
                  <span>Review reason</span>
                  <input
                    maxLength={1000}
                    onChange={(event) =>
                      setReasons((current) => ({
                        ...current,
                        [candidate.id]: event.target.value,
                      }))
                    }
                    placeholder="Verified GTIN and brand across market storefronts"
                    value={reasons[candidate.id] ?? ""}
                  />
                </label>
                <button
                  className="primary-button"
                  disabled={busyId !== null}
                  onClick={() => acceptCandidate(candidate)}
                  type="button"
                >
                  {busyId === candidate.id ? "Saving…" : "Link products"}
                </button>
                <button
                  className="danger-button"
                  disabled={busyId !== null}
                  onClick={() => rejectCandidate(candidate)}
                  type="button"
                >
                  Reject
                </button>
              </div>
            ) : null}
          </article>
        ))}
      </div>

      {response?.items.length === 0 ? (
        <p className="empty-state">No pending identity candidates.</p>
      ) : null}
    </section>
  );
}

function ProductReference({
  workspaceId,
  product,
}: {
  workspaceId: string;
  product: ProductIdentityCandidate["left_product"];
}) {
  return (
    <Link href={`/workspace/${workspaceId}/products/${product.id}`}>
      <strong>{product.title}</strong>
      <small>{product.canonical_key}</small>
    </Link>
  );
}

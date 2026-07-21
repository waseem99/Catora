"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiRequest, type Member, type RoleName } from "@/lib/auth";

const roles: RoleName[] = ["owner", "admin", "analyst", "reviewer", "viewer"];

type Props = {
  workspaceId: string;
  currentRole: RoleName;
};

export function MemberAdmin({ workspaceId, currentRole }: Props) {
  const [members, setMembers] = useState<Member[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canManage = currentRole === "owner" || currentRole === "admin";

  const load = useCallback(async () => {
    try {
      const response = await apiRequest<Member[]>(`/api/v1/workspaces/${workspaceId}/members`);
      setMembers(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load members");
    }
  }, [workspaceId]);

  useEffect(() => {
    apiRequest<Member[]>(`/api/v1/workspaces/${workspaceId}/members`)
      .then(setMembers)
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "Unable to load members"),
      );
  }, [workspaceId]);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError(null);
    setMessage(null);
    try {
      await apiRequest(`/api/v1/workspaces/${workspaceId}/invitations`, {
        method: "POST",
        body: JSON.stringify({ email: data.get("email"), role: data.get("role") }),
      });
      form.reset();
      setMessage("Invitation created and sent.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to invite member");
    }
  }

  async function changeRole(member: Member, role: RoleName) {
    setError(null);
    setMessage(null);
    try {
      await apiRequest(`/api/v1/workspaces/${workspaceId}/members/${member.membership_id}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      await load();
      setMessage(`${member.display_name}'s role was updated.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to update role");
    }
  }

  async function remove(member: Member) {
    if (!window.confirm(`Remove ${member.display_name} from this workspace?`)) return;
    setError(null);
    setMessage(null);
    try {
      await apiRequest(`/api/v1/workspaces/${workspaceId}/members/${member.membership_id}`, {
        method: "DELETE",
      });
      await load();
      setMessage(`${member.display_name} was removed.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to remove member");
    }
  }

  return (
    <section className="member-panel">
      <header>
        <p className="eyebrow">ACCESS CONTROL</p>
        <h2>Workspace members</h2>
        <p>Roles are enforced by the API. Owners cannot remove or demote the final owner.</p>
      </header>

      {canManage ? (
        <form className="invite-row" onSubmit={invite}>
          <label>
            Email
            <input name="email" type="email" required />
          </label>
          <label>
            Role
            <select name="role" defaultValue="viewer">
              {roles.filter((role) => currentRole === "owner" || role !== "owner").map((role) => (
                <option key={role} value={role}>{role}</option>
              ))}
            </select>
          </label>
          <button className="primary-button" type="submit">Invite member</button>
        </form>
      ) : null}

      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {message ? <p className="form-success" role="status">{message}</p> : null}

      <div className="member-list">
        {members.map((member) => (
          <article className="member-row" key={member.membership_id}>
            <div>
              <strong>{member.display_name}</strong>
              <span>{member.email}</span>
            </div>
            {canManage ? (
              <div className="member-actions">
                <label className="visually-hidden" htmlFor={`role-${member.membership_id}`}>
                  Role for {member.display_name}
                </label>
                <select
                  id={`role-${member.membership_id}`}
                  value={member.role}
                  onChange={(event) => void changeRole(member, event.target.value as RoleName)}
                >
                  {roles.filter((role) => currentRole === "owner" || role !== "owner").map((role) => (
                    <option key={role} value={role}>{role}</option>
                  ))}
                </select>
                <button className="danger-button" onClick={() => void remove(member)} type="button">
                  Remove
                </button>
              </div>
            ) : <small>{member.role}</small>}
          </article>
        ))}
      </div>
    </section>
  );
}

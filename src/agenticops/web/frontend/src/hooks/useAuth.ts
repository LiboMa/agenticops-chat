import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch, setAuthToken, clearAuthToken, getAuthToken } from "@/api/client";

interface LoginResponse {
  token: string;
  user_id: number;
  email: string;
  name: string | null;
  is_admin: boolean;
  expires_at: string;
}

interface AuthUser {
  user_id: number;
  email: string;
  name: string | null;
  is_admin: boolean;
}

function getStoredUser(): AuthUser | null {
  const raw = localStorage.getItem("aiops_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function useAuth() {
  const qc = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(getStoredUser);
  const isAuthenticated = !!getAuthToken() && !!user;

  const login = useCallback(async (email: string, password: string) => {
    const data = await apiFetch<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setAuthToken(data.token);
    const authUser: AuthUser = {
      user_id: data.user_id,
      email: data.email,
      name: data.name,
      is_admin: data.is_admin,
    };
    localStorage.setItem("aiops_user", JSON.stringify(authUser));
    // Nothing fetched as the previous user may show for this one (their private sessions included)
    qc.clear();
    setUser(authUser);
    return authUser;
  }, [qc]);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } catch {
      // Ignore errors on logout
    }
    clearAuthToken();
    setUser(null);
    // A full reload, not an in-app navigation: the query cache and the chat stream store hold this user's
    // data (private sessions and messages), which the next user in this tab must never see.
    window.location.assign(`${import.meta.env.BASE_URL}login`);
  }, []);

  return { user, isAuthenticated, login, logout };
}

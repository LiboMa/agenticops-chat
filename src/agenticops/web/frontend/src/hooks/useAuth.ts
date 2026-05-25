import { useState, useCallback } from "react";
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
    setUser(authUser);
    return authUser;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } catch {
      // Ignore errors on logout
    }
    clearAuthToken();
    setUser(null);
  }, []);

  return { user, isAuthenticated, login, logout };
}

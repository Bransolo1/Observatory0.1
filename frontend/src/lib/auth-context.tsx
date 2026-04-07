"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { auth as authApi, type AuthResponse, type OrgOption, type UserResponse } from "./api";

interface AuthState {
  user: UserResponse | null;
  orgs: OrgOption[];
  currentOrg: OrgOption | null;
  role: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, name: string, password: string, orgName?: string) => Promise<void>;
  logout: () => void;
  switchOrg: (orgId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function saveToken(res: AuthResponse) {
  localStorage.setItem("observatory_token", res.access_token);
  if (res.org_id) localStorage.setItem("observatory_org_id", res.org_id);
  if (res.role) localStorage.setItem("observatory_role", res.role);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    orgs: [],
    currentOrg: null,
    role: null,
    isLoading: true,
    isAuthenticated: false,
  });

  const loadUser = useCallback(async () => {
    try {
      const token = localStorage.getItem("observatory_token");
      if (!token) {
        setState((s) => ({ ...s, isLoading: false }));
        return;
      }
      const [user, orgs] = await Promise.all([authApi.me(), authApi.orgs()]);
      const orgId = localStorage.getItem("observatory_org_id");
      const currentOrg = orgs.find((o) => o.id === orgId) || orgs[0] || null;
      const role = currentOrg?.role || localStorage.getItem("observatory_role");
      setState({
        user,
        orgs,
        currentOrg,
        role,
        isLoading: false,
        isAuthenticated: true,
      });
    } catch {
      localStorage.removeItem("observatory_token");
      setState((s) => ({ ...s, isLoading: false }));
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const login = async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    saveToken(res);
    await loadUser();
  };

  const register = async (email: string, name: string, password: string, orgName?: string) => {
    const res = await authApi.register(email, name, password, orgName);
    saveToken(res);
    await loadUser();
  };

  const logout = () => {
    localStorage.removeItem("observatory_token");
    localStorage.removeItem("observatory_org_id");
    localStorage.removeItem("observatory_role");
    setState({
      user: null,
      orgs: [],
      currentOrg: null,
      role: null,
      isLoading: false,
      isAuthenticated: false,
    });
  };

  const switchOrg = async (orgId: string) => {
    const res = await authApi.selectOrg(orgId);
    saveToken(res);
    await loadUser();
  };

  return (
    <AuthContext.Provider value={{ ...state, login, register, logout, switchOrg, refresh: loadUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

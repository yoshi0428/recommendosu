import { useEffect, useState } from "react";
import { getCurrentUser, logout } from "../api/client";

export function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function checkAuthentication() {
      try {
        setUser(await getCurrentUser());
      } catch {
        // Backend unreachable: treat as logged out, so the login screen shows.
      } finally {
        setLoading(false);
      }
    }

    checkAuthentication();
  }, []);

  // Throws if the server refuses; the caller shows the error.
  async function handleLogout() {
    await logout();
    setUser(null);
  }

  return {
    user,
    loading,
    logout: handleLogout,
  };
}

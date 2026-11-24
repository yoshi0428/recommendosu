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
        // If the backend does not answer, treat the user as logged out, so
        // that the login screen shows.
      } finally {
        setLoading(false);
      }
    }

    checkAuthentication();
  }, []);

  // If the server refuses, this throws, and the caller shows the error.
  async function handleLogout() {
    await logout();
    setUser(null);
  }

  return { user, loading, logout: handleLogout };
}

import { useEffect, useState } from "react";
import { getCurrentUser, logout } from "../api/client";

// The auth state is one of:
//   { status: "checking", user: null }  the first check did not end yet
//   { status: "signedOut", user: null }
//   { status: "signedIn", user }
const CHECKING = { status: "checking", user: null };
const SIGNED_OUT = { status: "signedOut", user: null };
const signedIn = (user) => ({ status: "signedIn", user });

export function useAuth() {
  const [auth, setAuth] = useState(CHECKING);

  useEffect(() => {
    async function checkAuthentication() {
      try {
        const user = await getCurrentUser();
        setAuth(user ? signedIn(user) : SIGNED_OUT);
      } catch {
        // If the backend does not answer, treat the user as logged out, so
        // that the login screen shows.
        setAuth(SIGNED_OUT);
      }
    }

    checkAuthentication();
  }, []);

  // If the server refuses, this throws, and the caller shows the error.
  async function handleLogout() {
    await logout();
    setAuth(SIGNED_OUT);
  }

  return {
    user: auth.user,
    loading: auth.status === "checking",
    logout: handleLogout,
  };
}

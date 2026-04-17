import { useCallback, useEffect, useState, ReactNode } from 'react';
import type { User as SupabaseUser, Session } from '@supabase/supabase-js';
import { supabase } from '../lib/supabase';
import { ApiError, getCurrentUser, getApiConfigError } from '../lib/api';
import { AuthContext, AuthContextValue } from './AuthContext';
import type { User } from '../types/api';

function isAuthFailureStatus(status: number | null): boolean {
  return status === 401 || status === 403;
}

interface AuthProviderProps {
  children: ReactNode;
}

export default function AuthProvider({ children }: AuthProviderProps) {
  const [authUser, setAuthUser] = useState<SupabaseUser | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const accessToken = session?.access_token ?? null;
  const apiConfigError = getApiConfigError();

  useEffect(() => {
    let isActive = true;

    async function loadSession() {
      const { data } = await supabase.auth.getSession();

      if (!isActive) {
        return;
      }

      setSession(data.session);
      setAuthUser(data.session?.user ?? null);
      setIsLoading(false);
    }

    void loadSession();

    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setAuthUser(nextSession?.user ?? null);
    });

    return () => {
      isActive = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!accessToken || apiConfigError) {
      setCurrentUser(null);
      return undefined;
    }

    let isActive = true;

    async function loadCurrentUser() {
      try {
        const user = await getCurrentUser(accessToken!);

        if (isActive) {
          setCurrentUser(user);
        }
      } catch (error) {
        if (!isActive) {
          return;
        }

        const status = error instanceof ApiError ? error.status : null;
        if (isAuthFailureStatus(status)) {
          setCurrentUser(null);
          return;
        }

        // Transient failure (network / 5xx). Keep any existing currentUser in
        // place so a backend hiccup doesn't look like a silent sign-out.
        // eslint-disable-next-line no-console
        console.error('Failed to load current user', error);
      }
    }

    void loadCurrentUser();

    return () => {
      isActive = false;
    };
  }, [accessToken, apiConfigError]);

  const signInWithGoogle = useCallback(async () => {
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setAuthUser(null);
    setCurrentUser(null);
    setSession(null);
  }, []);

  const value: AuthContextValue = {
    authUser,
    currentUser,
    session,
    accessToken,
    isLoading,
    apiConfigError,
    signInWithGoogle,
    signOut,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

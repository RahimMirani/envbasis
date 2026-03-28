import { createContext } from 'react';
import type { User as SupabaseUser, Session } from '@supabase/supabase-js';
import type { User } from '../types/api';

export interface AuthContextValue {
  authUser: SupabaseUser | null;
  currentUser: User | null;
  session: Session | null;
  accessToken: string | null;
  isLoading: boolean;
  apiConfigError: string | null;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

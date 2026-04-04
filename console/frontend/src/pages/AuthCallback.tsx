import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { getStoredRedirectPath, clearStoredRedirectPath } from '../auth/redirect';

export default function AuthCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;

    async function handleCallback() {
      try {
        const { error: authError } = await supabase.auth.getSession();

        if (!isActive) {
          return;
        }

        if (authError) {
          setError(authError.message);
          return;
        }

        const redirectPath = getStoredRedirectPath();
        clearStoredRedirectPath();
        navigate(redirectPath || '/', { replace: true });
      } catch (err) {
        if (isActive) {
          setError(err instanceof Error ? err.message : 'Authentication failed.');
        }
      }
    }

    void handleCallback();

    return () => {
      isActive = false;
    };
  }, [navigate]);

  if (error) {
    return (
      <div className="auth-callback">
        <div className="auth-callback-error">
          <h2>Authentication Error</h2>
          <p>{error}</p>
          <button className="btn btn-primary" onClick={() => navigate('/login', { replace: true })}>
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-callback">
      <div className="auth-callback-loading">
        <div className="auth-callback-spinner" aria-hidden="true" />
        <p className="auth-callback-text">Please wait while we verify your session.</p>
      </div>
    </div>
  );
}

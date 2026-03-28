import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { getStoredRedirectPath, clearStoredRedirectPath } from '../auth/redirect';

export default function LoginPage() {
  const navigate = useNavigate();
  const { session, isLoading, signInWithGoogle, apiConfigError } = useAuth();
  const [isSigningIn, setIsSigningIn] = useState(false);

  useEffect(() => {
    if (!isLoading && session) {
      const redirectPath = getStoredRedirectPath();
      clearStoredRedirectPath();
      navigate(redirectPath || '/', { replace: true });
    }
  }, [isLoading, navigate, session]);

  const handleGoogleSignIn = async () => {
    setIsSigningIn(true);

    try {
      await signInWithGoogle();
    } catch {
      setIsSigningIn(false);
    }
  };

  if (isLoading) {
    return (
      <div className="login-page">
        <div className="login-card">
          <h1 className="login-title">EnvBasis</h1>
          <p className="login-subtitle">Checking session...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h1 className="login-title">EnvBasis</h1>
        <p className="login-subtitle">Secure secrets management for your team.</p>

        {apiConfigError && (
          <div className="auth-status auth-status-error" role="alert">
            <span>{apiConfigError}</span>
          </div>
        )}

        <button
          className="btn btn-primary btn-lg login-google-btn"
          onClick={handleGoogleSignIn}
          disabled={isSigningIn || Boolean(apiConfigError)}
        >
          {isSigningIn ? 'Redirecting...' : 'Sign in with Google'}
        </button>

        <p className="login-terms">
          By signing in, you agree to our Terms of Service and Privacy Policy.
        </p>
      </div>
    </div>
  );
}

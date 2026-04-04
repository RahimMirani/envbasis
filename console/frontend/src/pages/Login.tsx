import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import GoogleIcon from '../components/GoogleIcon';
import { useAuth } from '../auth/useAuth';
import { getStoredRedirectPath, clearStoredRedirectPath } from '../auth/redirect';
import { resetButtonGlow, updateButtonGlow } from '../lib/buttonGlow';

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
      <div className="auth-container">
        <div className="auth-glow auth-glow-1" aria-hidden="true" />
        <div className="auth-glow auth-glow-2" aria-hidden="true" />
        <div className="auth-card">
          <div className="auth-header">
            <div className="auth-logo">
              <img src="/envbasis-logo.png" alt="EnvBasis Logo" className="auth-logo-image" />
              <h2>EnvBasis</h2>
            </div>
            <h3>Welcome back</h3>
            <p>Checking your session.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <div className="auth-glow auth-glow-1" aria-hidden="true" />
      <div className="auth-glow auth-glow-2" aria-hidden="true" />
      <div className="auth-card">
        <div className="auth-header">
          <div className="auth-logo">
            <img src="/envbasis-logo.png" alt="EnvBasis Logo" className="auth-logo-image" />
            <h2>EnvBasis</h2>
          </div>
          <h3>Welcome back</h3>
          <p>Secure secrets management for your team.</p>
        </div>

        {apiConfigError && (
          <div className="auth-status auth-status-error" role="alert">
            <span>{apiConfigError}</span>
          </div>
        )}

        <button
          className="auth-google-btn"
          onClick={handleGoogleSignIn}
          onPointerMove={updateButtonGlow}
          onPointerLeave={resetButtonGlow}
          disabled={isSigningIn || Boolean(apiConfigError)}
        >
          {isSigningIn && <span className="spinner" aria-hidden="true" />}
          {!isSigningIn && <GoogleIcon />}
          <span>{isSigningIn ? 'Redirecting...' : 'Sign in with Google'}</span>
        </button>

        <div className="auth-footer">
          <p>By signing in, you agree to our Terms of Service and Privacy Policy.</p>
          <p>
            Need an account? <Link className="auth-link" to="/signup">Sign up</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

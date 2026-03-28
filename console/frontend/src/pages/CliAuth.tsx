import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Terminal, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import { resolveCliAuthCode, approveCliAuthCode, denyCliAuthCode } from '../lib/api';
import type { CliAuthRequest } from '../types/api';

type PageState = 'loading' | 'pending' | 'approved' | 'denied' | 'expired' | 'error';

export default function CliAuthPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { accessToken, session, isLoading: isAuthLoading, apiConfigError } = useAuth();
  const code = searchParams.get('code');

  const [pageState, setPageState] = useState<PageState>('loading');
  const [request, setRequest] = useState<CliAuthRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    if (!session) {
      navigate(`/login?redirect=${encodeURIComponent(`/cli/auth?code=${code || ''}`)}`, {
        replace: true,
      });
      return;
    }

    if (!code) {
      setPageState('error');
      setError('Missing authorization code.');
      return;
    }

    if (apiConfigError) {
      setPageState('error');
      setError(apiConfigError);
      return;
    }

    let isActive = true;

    async function loadRequest() {
      try {
        const data = await resolveCliAuthCode(code!, accessToken!);

        if (!isActive) {
          return;
        }

        setRequest(data);

        if (data.status === 'approved') {
          setPageState('approved');
        } else if (data.status === 'denied') {
          setPageState('denied');
        } else if (data.status === 'expired') {
          setPageState('expired');
        } else {
          setPageState('pending');
        }
      } catch (err) {
        if (!isActive) {
          return;
        }

        const apiError = err as Error & { status?: number };
        if (apiError.status === 404) {
          setPageState('expired');
        } else {
          setPageState('error');
          setError(apiError.message || 'Failed to load authorization request.');
        }
      }
    }

    void loadRequest();

    return () => {
      isActive = false;
    };
  }, [accessToken, apiConfigError, code, isAuthLoading, navigate, session]);

  const handleApprove = async () => {
    if (!code || !accessToken) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await approveCliAuthCode(code, accessToken);
      setPageState('approved');
    } catch (err) {
      setError((err as Error).message || 'Failed to approve request.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeny = async () => {
    if (!code || !accessToken) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await denyCliAuthCode(code, accessToken);
      setPageState('denied');
    } catch (err) {
      setError((err as Error).message || 'Failed to deny request.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderContent = () => {
    switch (pageState) {
      case 'loading':
        return (
          <>
            <div className="cli-auth-icon cli-auth-icon-loading">
              <Terminal size={32} />
            </div>
            <h1 className="cli-auth-title">Loading...</h1>
            <p className="cli-auth-subtitle">Fetching authorization request.</p>
          </>
        );

      case 'pending':
        return (
          <>
            <div className="cli-auth-icon">
              <Terminal size={32} />
            </div>
            <h1 className="cli-auth-title">Authorize CLI Access</h1>
            <p className="cli-auth-subtitle">
              A CLI session is requesting access to your EnvBasis account.
            </p>

            {request && (
              <div className="cli-auth-details">
                {request.client_name && (
                  <div className="cli-auth-detail">
                    <span className="cli-auth-label">Client</span>
                    <span className="cli-auth-value">{request.client_name}</span>
                  </div>
                )}
                {request.device_name && (
                  <div className="cli-auth-detail">
                    <span className="cli-auth-label">Device</span>
                    <span className="cli-auth-value">{request.device_name}</span>
                  </div>
                )}
                {request.platform && (
                  <div className="cli-auth-detail">
                    <span className="cli-auth-label">Platform</span>
                    <span className="cli-auth-value">{request.platform}</span>
                  </div>
                )}
                <div className="cli-auth-detail">
                  <span className="cli-auth-label">Code</span>
                  <span className="cli-auth-value mono">{request.user_code}</span>
                </div>
              </div>
            )}

            {error && (
              <div className="cli-auth-error" role="alert">
                {error}
              </div>
            )}

            <div className="cli-auth-actions">
              <button
                className="btn btn-secondary"
                onClick={handleDeny}
                disabled={isSubmitting}
              >
                Deny
              </button>
              <button
                className="btn btn-primary"
                onClick={handleApprove}
                disabled={isSubmitting}
              >
                {isSubmitting ? 'Approving...' : 'Approve'}
              </button>
            </div>
          </>
        );

      case 'approved':
        return (
          <>
            <div className="cli-auth-icon cli-auth-icon-success">
              <CheckCircle2 size={32} />
            </div>
            <h1 className="cli-auth-title">Access Approved</h1>
            <p className="cli-auth-subtitle">
              The CLI session has been authorized. You can close this tab and return to your
              terminal.
            </p>
          </>
        );

      case 'denied':
        return (
          <>
            <div className="cli-auth-icon cli-auth-icon-danger">
              <XCircle size={32} />
            </div>
            <h1 className="cli-auth-title">Access Denied</h1>
            <p className="cli-auth-subtitle">
              The CLI session was not authorized. You can close this tab.
            </p>
          </>
        );

      case 'expired':
        return (
          <>
            <div className="cli-auth-icon cli-auth-icon-warning">
              <AlertTriangle size={32} />
            </div>
            <h1 className="cli-auth-title">Request Expired</h1>
            <p className="cli-auth-subtitle">
              This authorization request has expired. Please start a new login from the CLI.
            </p>
          </>
        );

      case 'error':
        return (
          <>
            <div className="cli-auth-icon cli-auth-icon-danger">
              <XCircle size={32} />
            </div>
            <h1 className="cli-auth-title">Error</h1>
            <p className="cli-auth-subtitle">{error || 'An unexpected error occurred.'}</p>
            <button className="btn btn-primary" onClick={() => navigate('/')}>
              Go to Dashboard
            </button>
          </>
        );

      default:
        return null;
    }
  };

  return (
    <div className="cli-auth-page">
      <div className="cli-auth-card">{renderContent()}</div>
    </div>
  );
}

import { Navigate, Outlet, useLocation, useNavigate } from 'react-router';

import useAuth from '../hooks/useAuth.js';
import FullPageStatus from './FullPageStatus.jsx';

/**
 * Renders the nested routes only for a signed-in user, optionally restricted to `roles`.
 *
 * This only decides what the UI shows. The backend checks the role on every request,
 * so hiding a page here is never the thing that keeps data safe.
 */
export default function ProtectedRoute({ roles }) {
  const { user, status, retry } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  if (status === 'loading') {
    return <FullPageStatus loading message="Checking your session..." />;
  }
  if (status === 'error') {
    return (
      <FullPageStatus
        title="Can't reach the server"
        message="Your session could not be verified. Check that the backend is running."
        action={{ label: 'Retry', onClick: retry }}
      />
    );
  }
  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (roles && !roles.includes(user.role)) {
    return (
      <FullPageStatus
        title="Access denied"
        message="Your account doesn't have permission to view this page."
        action={{ label: 'Go to dashboard', onClick: () => navigate('/') }}
      />
    );
  }
  return <Outlet />;
}

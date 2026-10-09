import { Navigate, Outlet, useLocation } from 'react-router';

import useAuth from '../hooks/useAuth.js';
import FullPageStatus from './FullPageStatus.jsx';

/**
 * For pages only signed-out users should see (login, register). Once the user is
 * signed in, sends them back to the page they originally asked for, or home.
 */
export default function PublicOnlyRoute() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'loading') {
    return <FullPageStatus loading message="Checking your session..." />;
  }
  if (status === 'authenticated') {
    const destination = location.state?.from?.pathname || '/';
    return <Navigate to={destination} replace />;
  }
  return <Outlet />;
}

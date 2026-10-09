import { useNavigate } from 'react-router';

import FullPageStatus from '../components/FullPageStatus.jsx';

export default function NotFound() {
  const navigate = useNavigate();
  return (
    <FullPageStatus
      title="Page not found"
      message="The page you are looking for does not exist."
      action={{ label: 'Go to dashboard', onClick: () => navigate('/') }}
    />
  );
}

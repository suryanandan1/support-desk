import AutoAwesome from '@mui/icons-material/AutoAwesome';
import ChatOutlined from '@mui/icons-material/ChatOutlined';
import ConfirmationNumberOutlined from '@mui/icons-material/ConfirmationNumberOutlined';
import InsightsOutlined from '@mui/icons-material/InsightsOutlined';
import LibraryBooksOutlined from '@mui/icons-material/LibraryBooksOutlined';
import PeopleOutlined from '@mui/icons-material/PeopleOutlined';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import useAuth from '../hooks/useAuth.js';
import { ROLE_LABELS, ROLES } from '../utils/roles.js';

// What each role will be able to do. These features are built in later phases;
// the dashboard says so instead of showing pretend data.
const ROLE_FEATURES = {
  [ROLES.CUSTOMER]: [
    { icon: ChatOutlined, title: 'Ask the AI assistant', text: 'Answers grounded in our documentation, with sources.' },
    { icon: ConfirmationNumberOutlined, title: 'Track your tickets', text: 'Follow questions that were handed to our team.' },
  ],
  [ROLES.AGENT]: [
    { icon: ConfirmationNumberOutlined, title: 'Ticket queue', text: 'Pick up escalated questions and reply to customers.' },
    { icon: ChatOutlined, title: 'Conversation history', text: 'See what the AI already told the customer.' },
  ],
  [ROLES.ADMIN]: [
    { icon: LibraryBooksOutlined, title: 'Knowledge base', text: 'Upload and manage the documents the AI answers from.' },
    { icon: PeopleOutlined, title: 'Users and roles', text: 'Promote agents and deactivate accounts.' },
    { icon: InsightsOutlined, title: 'Analytics', text: 'Resolution rate, escalations, and feedback.' },
  ],
};

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function formatDate(value) {
  return value ? dateFormat.format(new Date(value)) : 'Never';
}

export default function Dashboard() {
  const { user } = useAuth();
  const firstName = user.full_name.split(' ')[0];
  const features = ROLE_FEATURES[user.role] ?? [];

  return (
    <Stack spacing={3} sx={{ maxWidth: 960 }}>
      <Box>
        <Typography variant="h4" component="h1">
          Welcome, {firstName}
        </Typography>
        <Typography color="text.secondary">
          Signed in as {ROLE_LABELS[user.role]}.
        </Typography>
      </Box>

      <Card>
        <CardContent>
          <Typography variant="h6" component="h2" gutterBottom>
            Your account
          </Typography>
          <Box
            component="dl"
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: '160px 1fr' },
              rowGap: 1,
              columnGap: 2,
              m: 0,
              '& dt': { color: 'text.secondary' },
              '& dd': { m: 0, overflowWrap: 'anywhere' },
            }}
          >
            <dt>Name</dt>
            <dd>{user.full_name}</dd>
            <dt>Email</dt>
            <dd>{user.email}</dd>
            <dt>Role</dt>
            <dd>
              <Chip size="small" color="primary" variant="outlined" label={ROLE_LABELS[user.role]} />
            </dd>
            <dt>Member since</dt>
            <dd>{formatDate(user.created_at)}</dd>
            <dt>Last sign-in</dt>
            <dd>{formatDate(user.last_login_at)}</dd>
          </Box>
        </CardContent>
      </Card>

      <Box>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1.5 }}>
          <AutoAwesome color="secondary" fontSize="small" />
          <Typography variant="h6" component="h2">
            Coming next
          </Typography>
        </Stack>
        <Box
          sx={{
            display: 'grid',
            gap: 2,
            gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(3, 1fr)' },
          }}
        >
          {features.map(({ icon: Icon, title, text }) => (
            <Card key={title}>
              <CardContent>
                <Icon color="primary" />
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mt: 1 }}>
                  {title}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {text}
                </Typography>
              </CardContent>
            </Card>
          ))}
        </Box>
      </Box>
    </Stack>
  );
}

import DashboardOutlined from '@mui/icons-material/DashboardOutlined';

import { ROLES } from '../utils/roles.js';

// Sidebar entries. Each later phase adds its pages here with the roles allowed to
// see them; the backend still enforces the same roles on every API call.
export const NAV_ITEMS = [
  {
    label: 'Dashboard',
    path: '/',
    icon: DashboardOutlined,
    roles: [ROLES.CUSTOMER, ROLES.AGENT, ROLES.ADMIN],
  },
];

export function navItemsForRole(role) {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}

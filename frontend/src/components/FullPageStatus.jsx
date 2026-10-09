import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';

/** Centered spinner or message for whole-page states (loading, unreachable, ...). */
export default function FullPageStatus({ loading = false, title, message, action }) {
  return (
    <Box
      role={loading ? 'status' : undefined}
      sx={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2,
        px: 2,
        textAlign: 'center',
      }}
    >
      {loading && <CircularProgress aria-label="Loading" />}
      {title && <Typography variant="h5">{title}</Typography>}
      {message && <Typography color="text.secondary">{message}</Typography>}
      {action && (
        <Button variant="contained" onClick={action.onClick} {...action.props}>
          {action.label}
        </Button>
      )}
    </Box>
  );
}

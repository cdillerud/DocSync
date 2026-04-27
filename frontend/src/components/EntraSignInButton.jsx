import { LogIn } from 'lucide-react';
import { Button } from './ui/button';

/**
 * Microsoft Entra ID sign-in button. Stylistically aligned with the existing
 * legacy LoginPage submit button. Caller wires onClick to entraLogin().
 */
export default function EntraSignInButton({ onClick, loading = false, disabled = false }) {
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className="w-full"
      data-testid="entra-signin-btn"
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <span className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
          Signing in with Microsoft…
        </span>
      ) : (
        <span className="flex items-center gap-2">
          <LogIn className="w-4 h-4" />
          Sign in with Microsoft
        </span>
      )}
    </Button>
  );
}

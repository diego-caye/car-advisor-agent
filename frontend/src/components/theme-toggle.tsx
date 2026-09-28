import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { type Theme, getInitialTheme, setStoredTheme } from '@/lib/theme'

export function ThemeToggle() {
  // The actual initial value was already applied by index.html's inline
  // script before this first render; this just syncs which icon to show.
  // Only persisting on change (not in an effect triggered by the initial
  // state) avoids writing to localStorage a preference the user never chose:
  // until they touch the button, the app keeps following the system theme.
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setStoredTheme(next)
    setTheme(next)
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="icon-sm"
      onClick={toggle}
      aria-label={theme === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
      title={theme === 'dark' ? 'Modo claro' : 'Modo oscuro'}
    >
      {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  )
}

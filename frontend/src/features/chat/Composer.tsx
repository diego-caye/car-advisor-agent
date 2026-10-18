import { type FormEvent, type KeyboardEvent, useState } from 'react'
import { SendHorizontal } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

type Props = {
  disabled: boolean
  onSend: (text: string) => void
}

export function Composer({ disabled, onSend }: Props) {
  const { t } = useTranslation()
  const [text, setText] = useState('')

  function submit(event?: FormEvent) {
    event?.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    setText('')
    onSend(trimmed)
  }

  // Enter sends and Shift+Enter makes a line break, which is what people
  // already expect from a chat. With an <input> there was no way to write
  // multiple lines.
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto flex w-full max-w-2xl items-end gap-2">
      <label className="sr-only" htmlFor="composer">
        {t('composer.label')}
      </label>
      <Textarea
        id="composer"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={t('composer.placeholder')}
        maxLength={2000}
        rows={1}
        autoComplete="off"
        className="max-h-40 min-h-11 flex-1 resize-none py-3 text-[15px]"
      />
      <Button
        type="submit"
        size="lg"
        disabled={disabled || !text.trim()}
        className="h-11 px-4"
      >
        <SendHorizontal aria-hidden="true" />
        {t('composer.send')}
      </Button>
    </form>
  )
}

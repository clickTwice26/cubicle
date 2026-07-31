import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight, Folder, Plus } from '../components/Icons'
import {
  Button,
  Card,
  EmptyState,
  Field,
  PAGE,
  PageHeader,
  Skeleton,
  useToast,
} from '../components/ui'
import { useCreateGroup, useGroups } from '../lib/hooks'
import { slugify } from '../lib/format'

export default function Playground() {
  const navigate = useNavigate()
  const toast = useToast()
  const { data: groups, isLoading } = useGroups()
  const createGroup = useCreateGroup()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')

  const submit = () => {
    createGroup.mutate(
      { name: name.trim() },
      {
        onSuccess: (group) => {
          toast.push(`Namespace ${group.ns} created`)
          setCreating(false)
          setName('')
          navigate(`/console/playground/${group.id}`)
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  return (
    <div className={PAGE}>
      <PageHeader
        title="Function playground"
        subtitle="Groups are namespaces. Every function inside a group inherits its namespace in the endpoint."
        action={
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
            New group
          </Button>
        }
      />

      {creating ? (
        <Card className="mb-5 border-accent p-6">
          <div className="mb-4 text-[15px] font-semibold">New group</div>
          <Field
            label="Group name"
            mono={false}
            autoFocus
            value={name}
            placeholder="Payments"
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && name.trim()) submit()
            }}
          />
          <div className="mt-3.5 flex items-center gap-2.5 rounded-[9px] border border-line bg-bg px-3.5 py-2.5">
            <span className="flex-none text-[11.5px] font-bold tracking-[0.05em] text-ink-3 uppercase">
              Namespace
            </span>
            <span className="overflow-x-auto font-mono text-[12.5px] whitespace-nowrap">
              /{slugify(name) || 'my-group'}/
            </span>
          </div>
          <div className="mt-4 flex gap-2.5">
            <Button
              variant="primary"
              onClick={submit}
              loading={createGroup.isPending}
              disabled={!name.trim()}
            >
              Create group
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setCreating(false)
                setName('')
              }}
            >
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-[132px]" />
          ))}
        </div>
      ) : groups && groups.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {groups.map((group) => (
            <Link key={group.id} to={`/console/playground/${group.id}`}>
              <Card className="p-5 transition hover:border-accent">
                <div className="mb-3 flex items-center gap-3">
                  <span className="grid h-8 w-8 flex-none place-items-center rounded-[9px] bg-accent-soft text-ink">
                    <Folder size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[15px] leading-tight font-semibold">
                      {group.name}
                    </div>
                    <div className="mt-0.5 font-mono text-[11.5px] text-ink-3">
                      {group.function_count} function{group.function_count === 1 ? '' : 's'}
                    </div>
                  </div>
                  <ChevronRight size={15} className="text-ink-3" />
                </div>
                <div className="truncate rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[11.5px] text-ink-2">
                  {group.base_url}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No groups yet"
          body="Create a group to get a namespace, then add functions under it."
          action={
            <Button
              variant="primary"
              icon={<Plus size={15} />}
              onClick={() => setCreating(true)}
            >
              New group
            </Button>
          }
        />
      )}
    </div>
  )
}

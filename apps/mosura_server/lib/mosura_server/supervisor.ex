defmodule MosuraServer.Supervisor do
  use Supervisor

  def start_link(opts) do
    Supervisor.start_link(__MODULE__, :ok, opts)
  end

  @impl true
  def init(:ok) do
    # TODO: configure add/remove projects
    children = [
      {DynamicSupervisor, name: MosuraServer.JiraSupervisor, strategy: :one_for_one},
      {MosuraServer.JiraProject, name: MosuraServer.JiraProject}
    ]

    Supervisor.init(children, strategy: :one_for_one)
  end
end

defmodule MosuraServer.Application do
  @moduledoc false

  use Application

  def start(_type, _args) do
    port = String.to_integer(System.get_env("PORT") || "8080")

    children = [
      {Task.Supervisor, name: MosuraServer.TaskSupervisor},
      Supervisor.child_spec({Task, fn -> MosuraServer.accept(port) end}, restart: :permanent)
    ]

    opts = [strategy: :one_for_one, name: MosuraServer.Supervisor]
    Supervisor.start_link(children, opts)
  end
end

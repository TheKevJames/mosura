defmodule MosuraServer.Application do
  @moduledoc false

  use Application

  def start(_type, _args) do
    children = [
      # {MosuraServer.Worker, arg}
    ]

    opts = [strategy: :one_for_one, name: MosuraServer.Supervisor]
    Supervisor.start_link(children, opts)
  end
end

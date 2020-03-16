defmodule MosuraServer do
  @moduledoc "OTP Application specification for MosuraServer"

  use Application

  @impl true
  def start(_type, _args) do
    port = Application.get_env(:mosura_server, :port)

    children = [
      {MosuraServer.Supervisor, name: MosuraServer.Supervisor},
      Plug.Cowboy.child_spec(scheme: :http, plug: MosuraServer.Endpoint, options: [port: port])
    ]

    opts = [strategy: :one_for_one, name: MosuraServer.Application]
    Supervisor.start_link(children, opts)
  end
end

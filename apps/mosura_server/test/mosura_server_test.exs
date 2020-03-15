defmodule MosuraServerTest do
  use ExUnit.Case
  doctest MosuraServer

  test "greets the world" do
    assert MosuraServer.hello() == :world
  end
end

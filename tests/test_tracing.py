def test_langfuse_callback_can_import() -> None:
    from langfuse.langchain import CallbackHandler

    assert CallbackHandler is not None

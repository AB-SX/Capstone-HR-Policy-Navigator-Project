
import json
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

# Mock LLM API for demonstration
class MockLLM:
    def __init__(self, model_name="small-model-1b"):
        self.model_name = model_name
        self.call_count = 0

    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        self.call_count += 1
        
        # Simulate small model failure modes based on prompt type
        if "Decompose" in prompt:
            return self._simulate_decomposition_failure(prompt)
        elif "Think step-by-step" in prompt:
            return self._simulate_cot_failure(prompt)
        elif "Examples:" in prompt:
            return self._simulate_few_shot_failure(prompt)
        
        return "Generic response"

    def _simulate_few_shot_failure(self, prompt: str) -> str:
        '''Small models often overfit to few-shot examples or lose track of the actual instruction'''
        if "Extract the entities" in prompt:
            # Typical failure: Copies the last example instead of solving the new input
            return '{"entities": ["Apple", "Tim Cook", "California"]}' 
        return "Failed to parse instruction"

    def _simulate_cot_failure(self, prompt: str) -> str:
        '''Small models often hallucinate logic or get stuck in repetitive loops during CoT'''
        if "math problem" in prompt.lower():
            # Typical failure: Flawed arithmetic hidden in confident text
            return (
                "Let's think step-by-step.\n"
                "1. We have 5 apples and buy 3 more. 5 + 3 = 8.\n"
                "2. Then we give away 2. 8 - 2 = 5.\n"
                "3. We multiply by 2. 5 * 2 = 12.\n"
                "The final answer is 12."
            )
        return "Step 1: Loop. Step 2: Loop."

    def _simulate_decomposition_failure(self, prompt: str) -> str:
        '''Small models struggle to maintain state across multiple sub-tasks in a single prompt'''
        # Typical failure: Answers task 1, ignores task 2 and 3 completely
        return (
            "Sub-task 1 Answer: The capital of France is Paris.\n"
            "Sub-task 2 Answer: Paris is known for the Eiffel Tower.\n"
            # Stops generating prematurely
        )

@dataclass
class PromptExperiment:
    name: str
    prompt_template: str
    description: str

class StrategyEvaluator:
    def __init__(self, llm: MockLLM):
        self.llm = llm
        self.logger = logging.getLogger(__name__)

    def evaluate_few_shot_structured(self, input_data: str) -> Dict[str, Any]:
        print("\n--- Testing Strategy 1: Few-Shot Structured Output ---")
        prompt = f'''
Task: Extract named entities from the text and output as JSON.

Examples:
Input: "Microsoft CEO Satya Nadella visited Washington."
Output: {{"entities": ["Microsoft", "Satya Nadella", "Washington"]}}

Input: "Apple was founded by Steve Jobs in California."
Output: {{"entities": ["Apple", "Steve Jobs", "California"]}}

Input: "{input_data}"
Output:
'''
        result = self.llm.generate(prompt)
        print(f"Model Output:\n{result}")
        print("Failure Mode Analysis: The small model exhibits 'Example Overfitting'. It ignores the input and blindly copies the structure and content of the last provided example.")
        return {"strategy": "few_shot", "output": result}

    def evaluate_chain_of_thought(self, input_data: str) -> Dict[str, Any]:
        print("\n--- Testing Strategy 2: Chain of Thought ---")
        prompt = f'''
Solve the following math problem. Think step-by-step before providing the final answer.

Problem: {input_data}
'''
        result = self.llm.generate(prompt)
        print(f"Model Output:\n{result}")
        print("Failure Mode Analysis: The small model exhibits 'Logical Hallucination/Arithmetic Failure'. It adopts the CoT persona but performs incorrect basic arithmetic (8-2=5, 5*2=12) while maintaining a confident tone.")
        return {"strategy": "cot", "output": result}

    def evaluate_decomposition(self, input_data: str) -> Dict[str, Any]:
        print("\n--- Testing Strategy 3: Decomposition Prompting ---")
        prompt = f'''
Decompose the following request into 3 distinct sub-tasks and answer them sequentially.

Request: {input_data}

Sub-task 1: Identify the main entity.
Sub-task 2: Provide a brief historical fact.
Sub-task 3: List 3 key economic drivers.
'''
        result = self.llm.generate(prompt)
        print(f"Model Output:\n{result}")
        print("Failure Mode Analysis: The small model exhibits 'Attention Decay / Premature Stopping'. It successfully handles the first one or two sub-tasks but completely forgets or ignores the final sub-tasks required by the prompt.")
        return {"strategy": "decomposition", "output": result}

def main():
    llm = MockLLM(model_name="tiny-llama-1b-mock")
    evaluator = StrategyEvaluator(llm)
    
    print(f"Starting Evaluation using model: {llm.model_name}")
    
    # Test 1: Structured Few-Shot
    evaluator.evaluate_few_shot_structured("Tesla recently opened a new Gigafactory in Texas under Elon Musk.")
    
    # Test 2: Chain of Thought
    evaluator.evaluate_chain_of_thought("I had 5 apples, bought 3 more, gave away 2, and then doubled my remaining amount. How many do I have?")
    
    # Test 3: Decomposition
    evaluator.evaluate_decomposition("Analyze the city of Paris.")

if __name__ == "__main__":
    main()
